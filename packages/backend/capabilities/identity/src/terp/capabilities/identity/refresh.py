"""The identity-side refresh-token store (ADR 0054): issue, rotate, revoke.

Auth owns the refresh *mechanics* (generation, keyed digest, cookie); this owns the
*rows*. It is wired into the auth login/refresh builders as the refresh seams (issue at
login, rotate at ``/refresh``) and into ``UsersService`` as the family revoker, so a
logout / deactivate / demote / password-reset kills the refresh tokens too — closing the
door a bare access-epoch bump would leave open (a still-live refresh cookie could otherwise
mint a fresh access token and defeat the revocation).

Writes ride the audited write unit (``enter_write_unit``), exactly like the durable
outbox / webhooks delivery infra: refresh tokens are session infrastructure, not an
audited domain aggregate, so they persist through the guarded chokepoint without a
``BaseService`` audit record of their own.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlmodel import Session, select

from terp.capabilities.auth import (
    RefreshRotation,
    generate_refresh_token,
    refresh_token_digest,
)
from terp.core import settings
from terp.core._internal.session_guard import enter_write_unit  # arch-allow-no-internal-imports: rotating refresh-token session infra must ride the audited write unit; the scope primitive is _internal so app modules cannot open it

from terp.capabilities.identity.models import RefreshToken

_logger = logging.getLogger("terp.capabilities.identity.refresh")


def _as_utc(value: datetime) -> datetime:
    """Normalize a stored datetime to timezone-aware UTC (SQLite may return it naive)."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class RefreshTokenService:
    """Issue / rotate / revoke rotating refresh tokens (ADR 0054)."""

    def issue(self, session: Session, user_id: uuid.UUID) -> str:
        """Open a new refresh-token family for *user_id*; return the raw token to cookie."""
        now = datetime.now(UTC)
        family_expires_at = now + timedelta(seconds=settings.REFRESH_FAMILY_TTL_SECONDS)
        with enter_write_unit() as outermost:
            raw = self._mint(session, user_id, uuid.uuid4(), family_expires_at, now)
            self._commit_if_outermost(session, outermost)
        return raw

    def rotate(self, session: Session, raw_token: str) -> RefreshRotation | None:
        """Validate and single-use rotate *raw_token*, or ``None`` when it must be refused.

        On success the presented token is consumed and a successor in the same family is
        returned. A token that is unknown, expired, or from an expired family is refused.
        A token spent within the last ``REFRESH_ROTATION_GRACE_SECONDS`` is treated as a
        **benign race** (two tabs refreshing, a client retry after a lost response) and
        rotates into a fresh successor instead of punishing the user. Past that window,
        **replaying a spent or revoked token is treated as theft** and revokes the whole
        family (reuse-detection), so a stolen copy cannot outlive the legitimate one.
        """
        digest = refresh_token_digest(raw_token)
        now = datetime.now(UTC)
        with enter_write_unit() as outermost:
            row = session.exec(
                select(RefreshToken)
                .where(RefreshToken.token_hash == digest)
                .with_for_update()
            ).first()
            if row is None:
                return None
            if row.revoked_at is not None or (
                row.used_at is not None and not self._within_reuse_grace(row, now)
            ):
                # A spent/revoked token replayed outside the race window — the theft
                # signal. Kill the whole family and surface it to operators: this is a
                # security event, not a routine 401.
                self._revoke_family(session, row.family_id, now)
                self._commit_if_outermost(session, outermost)
                _logger.warning(
                    "refresh_token_reuse_detected: revoked refresh-token family "
                    "%s for user %s (ADR 0054 reuse-detection)",
                    row.family_id,
                    row.user_id,
                )
                return None
            if _as_utc(row.expires_at) <= now or _as_utc(row.family_expires_at) <= now:
                return None
            if row.used_at is None:
                row.used_at = now
                session.add(row)  # arch-allow-mutations-emit-audit: refresh-token session infra (like the outbox) rides enter_write_unit, not BaseService — it is not a BaseTable domain aggregate
            new_raw = self._mint(
                session, row.user_id, row.family_id, _as_utc(row.family_expires_at), now
            )
            self._commit_if_outermost(session, outermost)
            return RefreshRotation(user_id=row.user_id, token=new_raw)

    def revoke_all_for_user(self, session: Session, user_id: uuid.UUID) -> None:
        """Revoke every live refresh token for *user_id* (logout / deactivate / reset).

        Wired as ``UsersService``'s refresh-revoker, so it runs in the same flow that bumps
        the access-token epoch — one security event kills both credentials.
        """
        now = datetime.now(UTC)
        with enter_write_unit() as outermost:
            rows = session.exec(
                select(RefreshToken).where(
                    RefreshToken.user_id == user_id,
                    RefreshToken.revoked_at.is_(None),  # type: ignore[attr-defined]
                ).with_for_update()
            ).all()
            self._revoke_rows(session, rows, now)
            self._commit_if_outermost(session, outermost)

    def purge_expired(self, session: Session) -> int:
        """Delete every row whose family absolute lifetime has passed; return the count.

        A refresh-token row is dead weight once its ``family_expires_at`` is in the past:
        it can never rotate again, and reuse-detection no longer needs it (a replay past the
        family cap is refused as expired before the spent-token check matters). Spent and
        revoked rows *inside* a live family are deliberately kept — they are the tripwire
        reuse-detection fires on. Run this from a scheduled job to bound table growth.
        """
        now = datetime.now(UTC)
        with enter_write_unit() as outermost:
            rows = session.exec(
                select(RefreshToken).where(RefreshToken.family_expires_at <= now)
            ).all()
            for row in rows:
                session.delete(row)  # arch-allow-mutations-emit-audit: retention purge of dead refresh-token session infra rows; rides enter_write_unit, not BaseService
            self._commit_if_outermost(session, outermost)
        return len(rows)

    @staticmethod
    def _within_reuse_grace(row: RefreshToken, now: datetime) -> bool:
        """Whether *row* was spent recently enough to be a benign race, not a replay."""
        if row.used_at is None:  # pragma: no cover - guarded by the caller
            return False
        grace = timedelta(seconds=settings.REFRESH_ROTATION_GRACE_SECONDS)
        return now - _as_utc(row.used_at) <= grace

    def _mint(
        self,
        session: Session,
        user_id: uuid.UUID,
        family_id: uuid.UUID,
        family_expires_at: datetime,
        now: datetime,
    ) -> str:
        """Create one token row in *family_id*; return the raw token (stored only by digest)."""
        raw = generate_refresh_token()
        expires_at = min(
            now + timedelta(seconds=settings.REFRESH_TOKEN_TTL_SECONDS), family_expires_at
        )
        session.add(  # arch-allow-mutations-emit-audit: refresh-token session infra (like the outbox) rides enter_write_unit, not BaseService — it is not a BaseTable domain aggregate
            RefreshToken(
                user_id=user_id,
                family_id=family_id,
                token_hash=refresh_token_digest(raw),
                expires_at=expires_at,
                family_expires_at=family_expires_at,
            )
        )
        return raw

    def _revoke_family(self, session: Session, family_id: uuid.UUID, now: datetime) -> None:
        """Revoke every live token in *family_id* — reuse-detection's blast radius."""
        rows = session.exec(
            select(RefreshToken).where(
                RefreshToken.family_id == family_id,
                RefreshToken.revoked_at.is_(None),  # type: ignore[attr-defined]
            ).with_for_update()
        ).all()
        self._revoke_rows(session, rows, now)

    @staticmethod
    def _revoke_rows(
        session: Session, rows: Sequence[RefreshToken], now: datetime
    ) -> None:
        """Stamp *rows* revoked at *now* and stage them for the enclosing write unit."""
        for row in rows:
            row.revoked_at = now
        session.add_all(rows)  # arch-allow-mutations-emit-audit: refresh-token session infra revocation write; rides enter_write_unit, not BaseService

    @staticmethod
    def _commit_if_outermost(session: Session, outermost: bool) -> None:
        """Commit only the outermost refresh write; a nested one joins the outer unit."""
        if outermost:
            session.commit()  # arch-allow-mutations-emit-audit: a standalone refresh-token write is its own committed unit; a nested one defers to the outer BaseService commit


__all__ = ["RefreshTokenService"]
