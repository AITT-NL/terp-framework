"""terp.capabilities.oidc — pluggable SSO via the OpenID Connect code flow (ADR 0058).

An opt-in capability implementing the Authorization Code flow with PKCE against any
spec-compliant OIDC provider — no vendor tenant baked in (design §5.5). It owns the
*protocol* only: the app wires the one identity seam
(``resolve_or_provision(session, claims) -> Principal | None``, backed by the identity
capability's federated store) and the auth capability's token seams, so an SSO login
mints a normal Terp session and every existing session control (revocation, refresh,
``/me``, ``/logout``) covers it unchanged.
"""

from __future__ import annotations

from terp.capabilities.oidc.client import (
    ALLOWED_ALGORITHMS,
    CLOCK_SKEW_LEEWAY_SECONDS,
    OIDCClient,
    ProviderUnavailableError,
)
from terp.capabilities.oidc.config import OIDCClaims, OIDCProviderConfig
from terp.capabilities.oidc.router import (
    IdentityResolver,
    SecretResolver,
    build_oidc_module,
    build_oidc_router,
)
from terp.capabilities.oidc.schemas import AuthorizationRequest, OIDCCallbackRequest
from terp.capabilities.oidc.state import (
    DEFAULT_STATE_TTL,
    InMemoryStateStore,
    PendingAuthorization,
    code_challenge_s256,
    generate_code_verifier,
)

__all__ = [
    "ALLOWED_ALGORITHMS",
    "AuthorizationRequest",
    "CLOCK_SKEW_LEEWAY_SECONDS",
    "DEFAULT_STATE_TTL",
    "IdentityResolver",
    "InMemoryStateStore",
    "OIDCCallbackRequest",
    "OIDCClaims",
    "OIDCClient",
    "OIDCProviderConfig",
    "PendingAuthorization",
    "ProviderUnavailableError",
    "SecretResolver",
    "build_oidc_module",
    "build_oidc_router",
    "code_challenge_s256",
    "generate_code_verifier",
]
