"""The persisted ``User`` table (identity capability).

``role`` is stored as the integer value of :class:`terp.core.Roles` (which is an
``IntEnum``), keeping the column a plain integer. ``token_version`` is the per-user
**token epoch** (ADR 0031): every issued access token carries the value it was minted
with, and bumping the column (on deactivate / role change / password reset / logout)
invalidates every outstanding token for that user at once.

``RefreshToken`` is the rotating refresh-token store (ADR 0054): one row per issued
refresh token, keyed by its keyed HMAC digest (never the raw token), grouped into a
``family_id`` so reuse-detection can revoke a whole login at once.

``FederatedIdentity`` links a user to an external SSO identity (ADR 0058): one row per
``(issuer, subject)`` pair — the stable OIDC identifier — unique so one external
identity can never resolve to two users. ``hashed_password`` is nullable so an SSO-only
user holds no local credential (password login refuses such users).

``ServiceAccount`` is the non-human subject (ADR 0088): a machine credential that
carries its own role, epoch and expiry, so an integration never has to borrow a
person's account.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, UniqueConstraint
from sqlmodel import Field

from terp.core import BaseTable, Roles


class User(BaseTable, table=True):
    __tablename__ = "identity_user"

    email: str = Field(max_length=320, index=True, unique=True)
    hashed_password: str | None = Field(default=None, max_length=256, nullable=True)
    role: int = Field(default=int(Roles.VIEWER))
    is_active: bool = Field(default=True)
    token_version: int = Field(default=0, nullable=False)


class RefreshToken(BaseTable, table=True):
    """A single rotating refresh token (ADR 0054) — stored by digest, never in the clear.

    The raw token lives only in the caller's httpOnly cookie; here it is a keyed HMAC
    digest (``token_hash``). Rotation consumes a token (``used_at``) and mints a successor
    in the same ``family_id``; a logout / deactivate / reuse-detection sets ``revoked_at``.
    ``expires_at`` is the per-token idle window; ``family_expires_at`` the absolute cap the
    whole family shares.
    """

    __tablename__ = "identity_refresh_token"

    user_id: uuid.UUID = Field(index=True, nullable=False)
    family_id: uuid.UUID = Field(index=True, nullable=False)
    token_hash: str = Field(max_length=128, index=True, unique=True, nullable=False)
    expires_at: datetime = Field(sa_type=DateTime(timezone=True), nullable=False)  # type: ignore[call-overload]
    family_expires_at: datetime = Field(sa_type=DateTime(timezone=True), nullable=False)  # type: ignore[call-overload]
    used_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True), nullable=True)  # type: ignore[call-overload]
    revoked_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True), nullable=True)  # type: ignore[call-overload]


class ServiceAccount(BaseTable, table=True):
    """A non-human principal: an integration that calls the API in its own name (ADR 0088).

    A machine has no email, no password and no browser, so it cannot use any of the
    login paths above. Without a row of its own it has to borrow a person's account —
    and since nobody wants to debug a permission error at 3am, the account it borrows
    is an admin. This table exists so the honest option is also the easy one.

    It is deliberately shaped like ``User`` where it matters: ``role``, ``is_active``
    and ``token_version`` mean exactly the same thing and are enforced by exactly the
    same code, so a service account is authorized and revoked like any other subject
    rather than through a second, weaker path. ``hashed_secret`` holds the client
    secret under the same password hasher; the plaintext exists once, at creation.

    ``expires_at`` is the one thing users do not have. A machine credential outlives
    the person who created it and the ticket that justified it, so it carries an end
    date by default — a credential nobody remembers is a credential nobody revokes.
    """

    __tablename__ = "identity_service_account"

    name: str = Field(max_length=128, nullable=False)
    description: str | None = Field(default=None, max_length=512, nullable=True)
    client_id: str = Field(max_length=64, index=True, unique=True, nullable=False)
    hashed_secret: str = Field(max_length=256, nullable=False)
    role: int = Field(default=int(Roles.VIEWER))
    is_active: bool = Field(default=True)
    token_version: int = Field(default=0, nullable=False)
    expires_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True), nullable=True)  # type: ignore[call-overload]
    last_used_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True), nullable=True)  # type: ignore[call-overload]


class FederatedIdentity(BaseTable, table=True):
    """One user's link to one external SSO identity (ADR 0058).

    Keyed by the OIDC-stable ``(issuer, subject)`` pair — **never** by email, which an
    IdP can reassign (the account-takeover vector ADR 0058 refuses). The unique
    constraint means one external identity resolves to at most one user.
    """

    __tablename__ = "identity_federated_identity"
    __table_args__ = (
        UniqueConstraint("issuer", "subject", name="uq_identity_federated_issuer_subject"),
    )

    user_id: uuid.UUID = Field(index=True, nullable=False)
    issuer: str = Field(max_length=512, nullable=False)
    subject: str = Field(max_length=255, nullable=False)
