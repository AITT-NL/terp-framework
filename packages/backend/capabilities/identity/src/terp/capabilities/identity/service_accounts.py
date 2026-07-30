"""Service accounts — the machine subject's ``authenticate`` (ADR 0088).

The symmetry with :mod:`terp.capabilities.identity.service` is the point. A machine
presents a client id and secret instead of an email and password, but everything
after that is the same code path: the credential resolves to a
:class:`~terp.core.Principal`, the principal flows through the same guard, and the
same token epoch revokes it. There is no second authorization model for machines —
that is exactly the thing this capability exists to prevent.

Two properties a human account does not have:

* **Expiry.** A machine credential outlives its justification. ``expires_at`` makes
  the end date part of the credential rather than part of somebody's memory.
* **A last-used stamp.** The question "is this integration still running?" has to be
  answerable before anyone will dare revoke a credential.

Every write goes through :class:`~terp.core.BaseService`, so provisioning, use and
revocation of a machine credential all land in the audit log. That is not incidental:
a service account is a standing grant of authority to something that cannot be asked
what it did, so the record of it is the only account anyone will ever get.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime

from sqlmodel import Session, select

from terp.capabilities.auth import (
    AccessTokenClaims,
    SubjectKind,
    hash_password,
    verify_password,
    verify_password_dummy,
)
from terp.core import (
    AuditAction,
    AuthenticationError,
    BaseService,
    PermissionModel,
    Principal,
)

from terp.capabilities.identity.models import ServiceAccount
from terp.capabilities.identity.schemas import (
    ServiceAccountCreate,
    ServiceAccountUpdate,
)

#: Bytes of entropy behind a generated client id / secret. 32 bytes is well past the
#: point where guessing is the attacker's best move, and the secret is never typed by
#: a human, so there is no usability reason to go shorter.
_TOKEN_BYTES = 32


class ServiceAccountService(
    BaseService[ServiceAccount, ServiceAccountCreate, ServiceAccountUpdate]
):
    """Provision, authenticate and revoke non-human subjects."""

    model = ServiceAccount

    def __init__(self, permission_model: PermissionModel | None = None) -> None:
        super().__init__()
        self._permission_model = permission_model or PermissionModel.default()

    def get_by_client_id(self, session: Session, client_id: str) -> ServiceAccount | None:
        return session.exec(
            select(ServiceAccount).where(ServiceAccount.client_id == client_id)
        ).first()

    def get_by_name(self, session: Session, name: str) -> ServiceAccount | None:
        """Look an account up by its human-readable name.

        For operator tooling only — never for authentication, which goes by client id.
        The name is not unique (nothing stops two integrations being called "sync"),
        so this returns the first match and is deliberately not a credential lookup.
        """
        return session.exec(
            select(ServiceAccount).where(ServiceAccount.name == name)
        ).first()

    def provision(
        self, session: Session, data: ServiceAccountCreate
    ) -> tuple[ServiceAccount, str]:
        """Create an account and return it with its **plaintext secret**.

        The secret is returned here and nowhere else, ever: only its hash is stored,
        so a leaked database does not hand over working credentials, and a lost secret
        is re-provisioned rather than recovered. Callers must treat the second element
        as write-once output — show it to the operator, never log it, never persist it.
        """
        secret = secrets.token_urlsafe(_TOKEN_BYTES)
        account = ServiceAccount(
            name=data.name,
            description=data.description,
            client_id=secrets.token_urlsafe(_TOKEN_BYTES),
            hashed_secret=hash_password(secret),
            role=data.role_rank,
            expires_at=data.expires_at,
        )
        return self._save(session, account, AuditAction.CREATED), secret

    def authenticate_client(
        self, session: Session, client_id: str, client_secret: str
    ) -> Principal | None:
        """Verify a client-credentials pair — the machine analog of ``authenticate``.

        Refuses an unknown, deactivated or **expired** account, and burns a dummy
        verify on the miss paths so an unknown client id costs the same as a wrong
        secret (otherwise the timing difference enumerates valid client ids).
        """
        account = self.get_by_client_id(session, client_id)
        if account is None or not account.is_active or self._is_expired(account):
            verify_password_dummy()
            return None
        if not verify_password(client_secret, account.hashed_secret):
            return None
        account.last_used_at = datetime.now(UTC)
        self._save(session, account, AuditAction.UPDATED)
        return self._principal_from(account)

    def token_version_for(self, session: Session, principal: Principal) -> int:
        """The account's current token epoch, so the mint signs it (ADR 0031).

        A missing account raises rather than returning ``0``: zero is a *plausible*
        epoch, so falling back to it would silently mint a token that outlives the
        revocation it was supposed to respect. The caller has just authenticated this
        principal in the same session, so absence here means something is wrong with
        the wiring, and the loud failure is the useful one.
        """
        account = session.get(ServiceAccount, principal.id)
        if account is None:
            raise AuthenticationError()
        return account.token_version

    def token_is_current(self, session: Session, claims: AccessTokenClaims) -> bool:
        """Whether *claims* still authorize a live machine session.

        The service-account half of the revocation validator: the account must exist,
        be active, be **unexpired**, and carry the current epoch. Expiry is re-checked
        here and not only at mint time, so an account that lapses mid-token stops
        working within the access token's lifetime rather than at its own convenience.
        """
        account = session.get(ServiceAccount, claims.subject)
        return (
            account is not None
            and account.is_active
            and not self._is_expired(account)
            and account.token_version == claims.token_version
        )

    def revoke(self, session: Session, account_id: uuid.UUID) -> bool:
        """Deactivate the account and bump its epoch, killing outstanding tokens now."""
        account = session.get(ServiceAccount, account_id)
        if account is None:
            return False
        account.is_active = False
        account.token_version += 1
        self._save(session, account, AuditAction.UPDATED)
        return True

    @staticmethod
    def _is_expired(account: ServiceAccount) -> bool:
        """Whether the credential's end date has passed.

        The stored value is normalised to UTC before comparing: a timezone-aware
        column round-trips aware on PostgreSQL but **naive** on SQLite, and a naive /
        aware comparison raises rather than answers. An expiry check that can throw is
        an expiry check nobody can rely on, so the ambiguity is resolved here (a naive
        stamp is UTC — it is the only thing this service ever writes) instead of being
        left to the driver.
        """
        if account.expires_at is None:
            return False
        expires_at = account.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        return expires_at <= datetime.now(UTC)

    def _principal_from(self, account: ServiceAccount) -> Principal:
        return Principal(
            id=account.id,
            role=self._permission_model.role_for_rank(account.role),
            kind=SubjectKind.SERVICE,
        )
