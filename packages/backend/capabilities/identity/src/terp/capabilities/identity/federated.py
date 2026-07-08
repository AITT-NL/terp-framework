"""Federated identity links — the identity backing for SSO logins (ADR 0058).

The OIDC capability owns *protocol*; this owns the *rows*: which local user an
external ``(issuer, subject)`` identity resolves to. Linking is keyed on that
OIDC-stable pair and **never** on email alone — an IdP can reassign an email, so an
email match would be an account-takeover vector.

Writes (a link, a JIT-provisioned user) route through the audited ``BaseService``
chokepoint, so every federated link and every provisioned account lands an audit
record. JIT provisioning is **off by default**: an app opts in with
``allow_provisioning=True``, and even then a provisioned account requires a
**verified** email claim, is created at the given (lowest, by default) rank with
**no local password** (``hashed_password=None`` — password login refuses it), and is
never auto-linked onto an existing user with the same email.
"""

from __future__ import annotations

import uuid

from sqlmodel import Field, Session, select

from terp.core import AuditAction, BaseSchema, BaseService, BaseUpdateSchema, Roles

from terp.capabilities.identity.models import FederatedIdentity, User


class FederatedIdentityLink(BaseSchema):
    """The create DTO for a federated link (an explicit admin/app-driven link)."""

    user_id: uuid.UUID
    issuer: str = Field(max_length=512)
    subject: str = Field(max_length=255)


class FederatedIdentityUpdate(BaseUpdateSchema):
    """A federated link is immutable: it is created or removed, never edited.

    Present only to satisfy the service's generic shape; it declares no editable
    fields, so an ``update`` can change nothing but still carries the OCC version.
    """


class FederatedIdentityService(
    BaseService[FederatedIdentity, FederatedIdentityLink, FederatedIdentityUpdate]
):
    """Resolve / link / (optionally) JIT-provision users for SSO logins."""

    model = FederatedIdentity

    def __init__(
        self,
        *,
        allow_provisioning: bool = False,
        provisioned_rank: int = int(Roles.VIEWER),
    ) -> None:
        self._allow_provisioning = allow_provisioning
        self._provisioned_rank = provisioned_rank

    def get_link(
        self, session: Session, issuer: str, subject: str
    ) -> FederatedIdentity | None:
        """The link row for ``(issuer, subject)``, or ``None``."""
        return session.exec(
            select(FederatedIdentity).where(
                FederatedIdentity.issuer == issuer,
                FederatedIdentity.subject == subject,
            )
        ).first()

    def link(
        self, session: Session, *, user_id: uuid.UUID, issuer: str, subject: str
    ) -> FederatedIdentity:
        """Link *user_id* to the external identity — an explicit, audited act."""
        row = FederatedIdentity(user_id=user_id, issuer=issuer, subject=subject)
        return self._save(session, row, AuditAction.CREATED)

    def resolve_or_provision(
        self,
        session: Session,
        *,
        issuer: str,
        subject: str,
        email: str | None,
        email_verified: bool,
    ) -> User | None:
        """The user an SSO login resolves to, or ``None`` when it must be refused.

        A linked identity resolves to its user only while that user is **active**. An
        unlinked identity is refused unless JIT provisioning is enabled — and even
        then only with a **verified** email claim, and never when a user with that
        email already exists (auto-linking by email is the account-takeover vector;
        link the existing account explicitly via :meth:`link` instead).
        """
        existing = self.get_link(session, issuer, subject)
        if existing is not None:
            user = session.get(User, existing.user_id)
            if user is None or not user.is_active:
                return None
            return user
        if not self._allow_provisioning:
            return None
        if not email or not email_verified:
            return None
        already = session.exec(select(User).where(User.email == email)).first()
        if already is not None:
            return None
        user = User(
            email=email,
            hashed_password=None,  # SSO-only: no local credential (ADR 0058)
            role=self._provisioned_rank,
        )
        self._save(session, user, AuditAction.CREATED)  # type: ignore[arg-type]
        self.link(session, user_id=user.id, issuer=issuer, subject=subject)
        return user


__all__ = [
    "FederatedIdentityLink",
    "FederatedIdentityService",
    "FederatedIdentityUpdate",
]
