"""Identity service — the ``authenticate`` backing for auth.

``authenticate`` looks a user up by email, verifies the password, and resolves the
user's stored rank to a :class:`~terp.core.Role` **through the app's
``PermissionModel``** — so a consumer-defined role (any rank the model registers)
authenticates without being coerced to the fixed three-tier ``Roles`` enum. The
model defaults to the compatibility ladder, so a 3-tier app needs no wiring; a
richer app passes its own ``PermissionModel`` (e.g. the control plane's).

It also backs **session revocation** (ADR 0031): :meth:`token_is_current` is the
``TokenValidator`` a revocable principal provider runs every request (the user must
exist, be active, and carry the current token epoch), and :meth:`principal_provider`
returns the one-call revocable ``get_principal`` the bundled stack wires by default.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from sqlmodel import Session, select

from terp.capabilities.auth import (
    AccessTokenClaims,
    CurrentUser,
    build_get_principal,
    verify_password,
    verify_password_dummy,
)
from terp.core import AuthenticationError, PermissionModel, Principal

from terp.capabilities.identity.models import FederatedIdentity, User


class IdentityService:
    def __init__(self, permission_model: PermissionModel | None = None) -> None:
        self._permission_model = permission_model or PermissionModel.default()

    def get_by_email(self, session: Session, email: str) -> User | None:
        return session.exec(select(User).where(User.email == email)).first()

    def get_by_id(self, session: Session, user_id: uuid.UUID) -> User | None:
        return session.get(User, user_id)

    def authenticate(
        self, session: Session, email: str, password: str
    ) -> Principal | None:
        user = self.get_by_email(session, email)
        if user is None or not user.is_active:
            # Burn a dummy Argon2 verify so an unknown/inactive email costs the same
            # as a real credential check — otherwise the response-time difference is
            # a remote user-enumeration side channel.
            verify_password_dummy()
            return None
        if user.hashed_password is None:
            # An SSO-only user (ADR 0058) holds no local credential: password login is
            # refused outright — there is nothing to verify, and accepting any input
            # here would turn federated accounts into passwordless local ones. The
            # dummy verify keeps the refusal timing-indistinguishable from a wrong
            # password, so the SSO-only status of an account does not leak either.
            verify_password_dummy()
            return None
        if not verify_password(password, user.hashed_password):
            return None
        return self._principal_from(user)

    def principal_for_id(self, session: Session, user_id: uuid.UUID) -> Principal | None:
        """Resolve an **active** subject's principal by id — the ``/refresh`` analog of
        :meth:`authenticate` (ADR 0054).

        ``/refresh`` has no password to check; it has a rotated ``user_id``. This rebuilds
        the :class:`~terp.core.Principal` (role resolved from the store through the app's
        ``PermissionModel``) only for a still-**active** user, so a deactivated subject
        cannot refresh into a fresh access token even in the window before the revoke lands
        — defense in depth atop the refresh-family revoke wired on deactivation.
        """
        user = self.get_by_id(session, user_id)
        if user is None or not user.is_active:
            return None
        return self._principal_from(user)

    def principal_for_federated(
        self, session: Session, issuer: str, subject: str
    ) -> Principal | None:
        """Resolve an **active** subject's principal by federated identity (ADR 0058).

        The SSO analog of :meth:`authenticate`: an OIDC callback has no password, it has
        the validated ID token's ``(issuer, subject)`` pair. This follows the
        ``identity_federated_identity`` link — never an email match, which an IdP can
        reassign (the account-takeover vector) — and rebuilds the principal only for a
        still-**active** linked user, so a deactivated subject cannot log in via SSO.
        """
        link = session.exec(
            select(FederatedIdentity).where(
                FederatedIdentity.issuer == issuer,
                FederatedIdentity.subject == subject,
            )
        ).first()
        if link is None:
            return None
        return self.principal_for_id(session, link.user_id)

    def principal_for_user(self, session: Session, user: User) -> Principal:
        """The typed principal for an already-resolved **live** *user* row.

        The public composition seam an SSO wiring uses after
        ``FederatedIdentityService.resolve_or_provision`` hands back a user: the stored
        rank resolves to a named role through the app's ``PermissionModel``, exactly as
        ``authenticate`` does.
        """
        del session  # symmetric signature with the other resolvers; the row is live
        return self._principal_from(user)

    def _principal_from(self, user: User) -> Principal:
        """Build the typed principal for *user*, resolving its stored rank to a role."""
        return Principal(id=user.id, role=self._permission_model.role_for_rank(user.role))

    def current_user(self, session: Session, principal: Principal) -> CurrentUser:
        """The authenticated caller's own identity — the ``GET /me`` resolver (ADR 0044).

        Wired as the auth ``CurrentUserResolver`` via
        ``build_me_module(IdentityService(...).current_user)``. It reads the **live** row
        for ``principal.id`` and resolves its stored rank to a named role through the
        app's ``PermissionModel`` — so ``/me`` reflects the store and the wire carries both
        the numeric ``role_rank`` and a display ``role_name``. A missing row (a token for a
        since-removed subject reaching the *stateless* provider) is rejected as
        unauthenticated rather than rendered.
        """
        user = self.get_by_id(session, principal.id)
        if user is None:
            raise AuthenticationError()
        role = self._permission_model.role_for_rank(user.role)
        return CurrentUser(
            id=user.id,
            email=user.email,
            role_rank=role.rank,
            role_name=role.name,
        )

    def token_version_for(self, session: Session, principal: Principal) -> int:
        """The principal's current token epoch, so login signs it (ADR 0031).

        The ``token_version_resolver`` the login builder calls after authentication: a
        token minted at the user's *current* epoch is valid; without signing it, the
        first token issued after any revoking change would be instantly stale. A missing
        user resolves to ``0`` (the default epoch); the caller just authenticated, so the
        row exists in practice.
        """
        user = self.get_by_id(session, principal.id)
        return user.token_version if user is not None else 0

    def token_is_current(self, session: Session, claims: AccessTokenClaims) -> bool:
        """Whether *claims* still authorize a live session — the revocation check.

        The ``TokenValidator`` a revocable principal provider runs on every request: the
        subject must still exist, be **active** (the mid-session ``is_active`` re-check —
        a deactivated user is rejected at once, not at next login), **and** carry the
        user's **current** token epoch (a deactivate / demote / re-tenant / password-reset
        / logout bumps it, instantly invalidating older tokens). One indexed primary-key
        lookup answers all three.
        """
        user = self.get_by_id(session, claims.subject)
        return (
            user is not None
            and user.is_active
            and user.token_version == claims.token_version
        )

    def principal_provider(self) -> Callable[..., Principal | None]:
        """The one-call **revocable** ``get_principal`` seam for ``create_app``.

        Wires :meth:`token_is_current` into ``build_get_principal``, so the bundled stack
        gets prompt revocation + the mid-session ``is_active`` re-check with a single
        ``principal_provider=IdentityService(...).principal_provider()`` — and the
        returned provider is marked, so ``create_app(require_token_revocation=True)``
        accepts it (ADR 0031).
        """
        return build_get_principal(token_validator=self.token_is_current)
