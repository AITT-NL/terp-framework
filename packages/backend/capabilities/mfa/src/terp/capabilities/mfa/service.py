"""The second-factor service: enrol, confirm, verify, disable.

Every write here goes through :class:`~terp.core.BaseService`'s audited chokepoint, so
enrolling and disabling a factor land in the trail like any other change. That matters
more than usual for this table: *disabling* a second factor is the single most useful
thing an attacker who has taken an account can do to keep it, and a disable that left no
record would be invisible.

Verifying is a **write too**, which reads as a surprise and is not one: a second factor
that can be used twice is not a second factor, so accepting a code has to record that it
was accepted. A TOTP code moves the enrolment's high-water mark; a recovery code is
stamped spent. Both go through the same chokepoint as everything else here — the
``mutations_emit_audit`` rule requires it, and a factor being exercised is a thing the
trail should carry. It happens during a login, before there is a session at all, so the
actor on those records is the login rather than a signed-in person.
"""

from __future__ import annotations

import datetime
import uuid

from sqlmodel import Session, select

from terp.core import AppError, BaseService

from terp.capabilities.mfa import recovery, totp
from terp.capabilities.mfa.models import MfaEnrolment, MfaRecoveryCode
from terp.capabilities.mfa.schemas import (
    MfaEnrolmentCreate,
    MfaEnrolmentUpdate,
    MfaSecretIssued,
)
from terp.capabilities.mfa.sealing import seal_secret, unseal_secret


class MfaAlreadyEnrolledError(AppError):
    """409 — this subject already has a live second factor.

    Refused rather than silently replaced: overwriting a live enrolment is exactly the
    move an attacker makes with a stolen session, and it would read as an ordinary
    "set up authenticator" request. Replacing one means disabling it first, which is a
    separate, audited act.
    """

    status_code = 409
    code = "mfa_already_enrolled"
    default_message = "A second factor is already enrolled for this account."


class MfaNotEnrolledError(AppError):
    """404 — there is no enrolment to confirm, verify against, or disable."""

    status_code = 404
    code = "mfa_not_enrolled"
    default_message = "No second factor is enrolled for this account."


class MfaCodeInvalidError(AppError):
    """401 — the code did not verify.

    One error for a wrong TOTP code and a wrong recovery code, on purpose: telling a
    caller *which* of the two they got wrong tells them which one they are closer to,
    and neither answer helps somebody typing their own code.
    """

    status_code = 401
    code = "mfa_code_invalid"
    default_message = "That code is not valid."


def _utc_now() -> datetime.datetime:
    """UTC ``now`` provider — private so tests can drive the clock."""
    return datetime.datetime.now(datetime.UTC)


class MfaService(BaseService[MfaEnrolment, MfaEnrolmentCreate, MfaEnrolmentUpdate]):
    model = MfaEnrolment

    def enrolment_for(self, session: Session, user_id: uuid.UUID) -> MfaEnrolment | None:
        """This subject's enrolment row, confirmed or not."""
        return session.exec(
            select(MfaEnrolment).where(MfaEnrolment.user_id == user_id)
        ).first()

    def is_enrolled(self, session: Session, user_id: uuid.UUID) -> bool:
        """Whether a **confirmed** second factor stands between this subject and a session.

        Only a confirmed enrolment counts. A started-but-unproved one must not gate a
        login, or a mis-scanned QR code becomes a lockout.
        """
        enrolment = self.enrolment_for(session, user_id)
        return enrolment is not None and enrolment.confirmed_at is not None

    def begin_enrolment(
        self, session: Session, user_id: uuid.UUID, *, account: str, issuer: str
    ) -> MfaSecretIssued:
        """Issue a secret and recovery codes. The plaintext is returned exactly once.

        An *unconfirmed* row is replaced rather than refused: somebody who started an
        enrolment, closed the tab and came back has no way to recover the first secret,
        and refusing them would leave a row nobody can confirm and nobody can clear. A
        *confirmed* row is refused (see :class:`MfaAlreadyEnrolledError`).
        """
        existing = self.enrolment_for(session, user_id)
        if existing is not None:
            if existing.confirmed_at is not None:
                raise MfaAlreadyEnrolledError()
            self._purge_recovery_codes(session, existing.id)
            self.delete(session, existing.id)

        secret = totp.generate_secret()
        enrolment = self.create(
            session,
            MfaEnrolmentCreate(user_id=user_id, secret=seal_secret(secret)),
        )
        codes = recovery.generate_codes()
        for code in codes:
            self._save_recovery_code(session, enrolment.id, recovery.hash_code(code))
        return MfaSecretIssued(
            secret=secret,
            provisioning_uri=totp.provisioning_uri(secret, account=account, issuer=issuer),
            recovery_codes=codes,
        )

    def confirm_enrolment(self, session: Session, user_id: uuid.UUID, code: str) -> MfaEnrolment:
        """Prove the secret arrived intact, and make the factor live."""
        enrolment = self.enrolment_for(session, user_id)
        if enrolment is None:
            raise MfaNotEnrolledError()
        if enrolment.confirmed_at is not None:
            raise MfaAlreadyEnrolledError()
        step = totp.verify_step(unseal_secret(enrolment.secret), code)
        if step is None:
            raise MfaCodeInvalidError()
        # The confirming code is spent by confirming. Recording it here is what stops it
        # being handed straight back as the first login factor, which is a replay across
        # two endpoints rather than two calls to one.
        return self.update(
            session,
            enrolment.id,
            MfaEnrolmentUpdate(
                confirmed_at=_utc_now(), last_used_step=step, version=enrolment.version
            ),
        )

    def verify(self, session: Session, user_id: uuid.UUID, code: str) -> bool:
        """Whether *code* satisfies this subject's second factor.

        Accepts a TOTP code or an unspent recovery code, and spends the latter. Returns
        ``False`` rather than raising for a subject with no confirmed enrolment: the
        caller is the login route, and "this account has no second factor" is its
        question to ask beforehand, not an error to handle here.
        """
        enrolment = self.enrolment_for(session, user_id)
        if enrolment is None or enrolment.confirmed_at is None:
            return False
        step = totp.verify_step(unseal_secret(enrolment.secret), code)
        if step is not None:
            return self._spend_step(session, enrolment, step)
        return self._consume_recovery_code(session, enrolment.id, code)

    def disable(self, session: Session, user_id: uuid.UUID) -> None:
        """Remove the factor and every recovery code with it (an audited delete)."""
        enrolment = self.enrolment_for(session, user_id)
        if enrolment is None:
            raise MfaNotEnrolledError()
        self._purge_recovery_codes(session, enrolment.id)
        self.delete(session, enrolment.id)

    def _purge_recovery_codes(self, session: Session, enrolment_id: uuid.UUID) -> None:
        """Delete this enrolment's codes through the audited chokepoint.

        Explicit, rather than leaning on the foreign key's ``ON DELETE CASCADE``. The
        cascade is declared and is the right backstop, but it only fires where the
        database enforces foreign keys -- SQLite does not, unless asked -- so a service
        that relied on it would leave live recovery codes behind on one backend and not
        another. A spent-looking factor whose codes still authenticate is the worst of
        the available failures, so the deletion is stated here and the cascade is
        defence in depth.
        """
        for row in session.exec(
            select(MfaRecoveryCode).where(MfaRecoveryCode.enrolment_id == enrolment_id)
        ).all():
            self._remove(session, row)

    def _save_recovery_code(
        self, session: Session, enrolment_id: uuid.UUID, code_hash: str
    ) -> None:
        """Persist one code digest through the audited chokepoint."""
        from terp.core import AuditAction

        self._save(
            session,
            MfaRecoveryCode(enrolment_id=enrolment_id, code_hash=code_hash),
            AuditAction.CREATED,
        )

    def _spend_step(self, session: Session, enrolment: MfaEnrolment, step: int) -> bool:
        """Accept *step* once, and never again for this enrolment."""
        from terp.core import AuditAction

        # `<=`, not `==`: the drift window reaches one step BACK, so after a code from the
        # current step is spent the previous step is still inside the window and its code
        # would otherwise verify. Refusing everything at or below the high-water mark closes
        # the window behind the caller rather than just the one code they used.
        if enrolment.last_used_step is not None and step <= enrolment.last_used_step:
            return False
        enrolment.last_used_step = step
        # Through the chokepoint, like every other mutation here: `mutations_emit_audit`
        # requires it, and a second factor being exercised is a thing the trail should carry.
        self._save(session, enrolment, AuditAction.UPDATED)
        return True

    def _consume_recovery_code(
        self, session: Session, enrolment_id: uuid.UUID, code: str
    ) -> bool:
        """Spend an unspent recovery code matching *code*, if there is one.

        Every candidate is compared even after a match is found, so the work does not
        depend on which code was presented.
        """
        from terp.core import AuditAction

        rows = session.exec(
            select(MfaRecoveryCode).where(
                MfaRecoveryCode.enrolment_id == enrolment_id,
                MfaRecoveryCode.used_at.is_(None),  # type: ignore[union-attr]
            )
        ).all()
        found: MfaRecoveryCode | None = None
        for row in rows:
            if recovery.matches(code, row.code_hash) and found is None:
                found = row
        if found is None:
            return False
        found.used_at = _utc_now()
        self._save(session, found, AuditAction.UPDATED)
        return True


__all__ = [
    "MfaAlreadyEnrolledError",
    "MfaCodeInvalidError",
    "MfaNotEnrolledError",
    "MfaService",
]
