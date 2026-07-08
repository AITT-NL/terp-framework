"""Auth wiring for the example app — login backed by the identity store.

The ``auth`` capability is decoupled from where users live; here its
``authenticate`` callback is backed by the **identity** capability's persisted
store. ``IdentityService`` is given the control plane's ``PermissionModel`` so a
user's stored rank resolves to a named role through the app's own ladder
(role-model-agnostic, ADR 0022).

The login also signs a **tenant** claim: the example maps a user to a tenant by
their email domain (everyone ``@acme.test`` shares one tenant, ``@globex.test``
another), through the ``tenant_resolver`` seam — so a real ``/auth/login`` yields a
token that the wired ``TenantMiddleware`` binds, and the tenant-scoped ``projects``
module is isolated per tenant end to end. A real app would resolve the tenant from
its own membership store; the domain mapping keeps the example self-contained.

Session management (ADR 0031) is dogfooded too: ``principal_provider`` is the
**revocable** seam (it re-checks ``is_active`` + the token epoch every request via the
store), login signs the current epoch (``token_version_resolver``) and exposes
``/logout`` (``revoke_sessions``), and a per-account ``LoginThrottle`` locks out
credential-stuffing. ``main.build()`` sets ``require_token_revocation=True`` over this
provider, so the secure path is the default and a refactor that drops it fails the boot.
"""

from __future__ import annotations

import uuid

from sqlmodel import Session

from terp.capabilities.auth import LoginThrottle, build_login_module, build_me_module
from terp.capabilities.identity import (
    FederatedIdentityService,
    IdentityService,
    RefreshTokenService,
)
from terp.capabilities.oidc import OIDCClaims, OIDCProviderConfig, build_oidc_module
from terp.capabilities.users import UsersService
from terp.core import InMemoryThrottleStore, Principal, get_settings

from control_plane import control_plane

_identity = IdentityService(control_plane.permissions)
# Rotating refresh tokens (ADR 0054): issued at login, rotated at /refresh, and revoked (with
# the access-token epoch) on logout / deactivate / demote / reset via the UsersService seam.
_refresh = RefreshTokenService()
_users = UsersService(refresh_revoker=_refresh.revoke_all_for_user)

# A single throttle store backs both the request rate limiter and the login lockout
# (ADR 0036). In-memory here (one process), but passing the same store to both controls
# is the seam a multi-instance deployment swaps for a shared backend so the limits stay
# correct across workers; ``main.build()`` hands it to ``create_app(throttle_store=…)``.
throttle_store = InMemoryThrottleStore()

# The revocable get_principal seam: each request re-validates the bearer against the
# store (active + current token epoch), so a deactivated / demoted / re-tenanted /
# password-reset / logged-out user's token is rejected mid-session. It is marked, so
# create_app(require_token_revocation=True) accepts it.
principal_provider = _identity.principal_provider()

# Per-account login lockout (on by default). A module global so the e2e suite can reset
# its in-process counters between cases (the login module is itself a module global).
login_throttle = LoginThrottle(store=throttle_store)

# A fixed namespace, so a tenant id is a deterministic function of the email domain.
_TENANT_NAMESPACE = uuid.UUID("6f9619ff-8b86-d011-b42d-00cf4fc964ff")


def tenant_id_for_email(email: str) -> uuid.UUID:
    """The tenant a user belongs to, derived from their email domain (example policy).

    A deterministic ``uuid5`` of the domain, exposed so ``terp seed`` can create
    tenant-scoped rows under exactly the tenant a real login for that user would bind.
    """
    domain = email.partition("@")[2] or email
    return uuid.uuid5(_TENANT_NAMESPACE, domain)


def _tenant_from_email_domain(session: Session, principal: Principal) -> uuid.UUID | None:
    """Map the authenticated user to a tenant by their email domain (example policy)."""
    user = _identity.get_by_id(session, principal.id)
    if user is None:
        return None
    return tenant_id_for_email(user.email)


login_module = build_login_module(
    _identity.authenticate,
    tenant_resolver=_tenant_from_email_domain,
    token_version_resolver=_identity.token_version_for,
    revoke_sessions=_users.revoke_sessions,
    throttle=login_throttle,
    refresh_issuer=_refresh.issue,
    refresh_rotator=_refresh.rotate,
    principal_resolver=_identity.principal_for_id,
    require_refresh=True,
)

# The who-am-I endpoint (ADR 0044): GET /api/v1/me returns the authenticated caller's own
# identity, resolved through the same revocable provider, so the frontend's session
# contract has a server-validated current user (the access token carries no email).
me_module = build_me_module(_identity.current_user)

# --------------------------------------------------------------------------- #
# SSO via OIDC (ADR 0058) — dogfooding the pluggable-provider seam.
# --------------------------------------------------------------------------- #
# The example points at the dev-workbench IdP shape (a local dex instance); the
# values are development placeholders, not credentials. Identity resolution rides
# the federated store: a validated (issuer, subject) pair resolves to a linked
# user, and JIT provisioning is enabled so a first SSO login with a verified email
# creates a viewer-ranked, SSO-only account (no local password).
_federated = FederatedIdentityService(allow_provisioning=True)


def _resolve_sso_principal(session: Session, claims: OIDCClaims) -> Principal | None:
    """The OIDC identity seam: validated claims -> a principal, via the federated store."""
    user = _federated.resolve_or_provision(
        session,
        issuer=claims.issuer,
        subject=claims.subject,
        email=claims.email,
        email_verified=claims.email_verified,
    )
    if user is None:
        return None
    return _identity.principal_for_user(session, user)


# The dev-workbench IdP (a local http dex) is a development-only provider: the OIDC
# capability fails closed on a plaintext issuer in production, so the example builds
# the SSO module only outside production (a real deployment configures an https
# provider and mounts it unconditionally). The SSO callback shares the app-wide
# throttle store (ADR 0036) and mints its session through the exact seams /login uses
# (tenant claim, token epoch, refresh cookie) — one session/revocation story for both
# auth paths.
oidc_module = (
    None
    if get_settings().is_production
    else build_oidc_module(
        [
            OIDCProviderConfig(
                name="dex",
                issuer="http://localhost:5556/dex",
                client_id="terp-example",
                client_secret="dev-placeholder-not-a-secret",
                redirect_uri="http://localhost:5173/auth/callback/dex",
            )
        ],
        _resolve_sso_principal,
        tenant_resolver=_tenant_from_email_domain,
        token_version_resolver=_identity.token_version_for,
        refresh_issuer=_refresh.issue,
        throttle=LoginThrottle(store=throttle_store),
    )
)
