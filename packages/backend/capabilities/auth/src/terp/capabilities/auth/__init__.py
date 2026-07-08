"""terp.capabilities.auth — authentication (Argon2 hashing + JWT + ``get_principal``).

The first opt-in capability. It fills the kernel's ``get_principal`` seam with a
real Bearer-JWT provider and supplies password hashing + a login router. It is
**decoupled from the user store**: the app (or, later, the identity capability)
supplies an ``authenticate`` callback, so auth never needs to know where users
live.
"""

from __future__ import annotations

from terp.capabilities.auth.deps import (
    TokenValidator,
    build_get_principal,
    get_principal,
    tenant_from_bearer,
)
from terp.capabilities.auth.hashing import (
    hash_password,
    verify_password,
    verify_password_dummy,
)
from terp.capabilities.auth.refresh import (
    RefreshRotation,
    clear_refresh_cookie,
    generate_refresh_token,
    refresh_token_digest,
    set_refresh_cookie,
)
from terp.capabilities.auth.router import (
    Authenticator,
    CurrentUserResolver,
    LoginTenantResolver,
    PrincipalResolver,
    RefreshIssuer,
    RefreshRotator,
    TokenRevoker,
    TokenVersionResolver,
    build_login_module,
    build_login_router,
    build_me_module,
    build_me_router,
)
from terp.capabilities.auth.schemas import AccessToken, CurrentUser, LoginRequest
from terp.capabilities.auth.throttle import AccountLockedError, LoginThrottle
from terp.capabilities.auth.tokens import (
    TOKEN_AUDIENCE,
    TOKEN_ISSUER,
    AccessTokenClaims,
    create_access_token,
    decode_access_token,
)

__all__ = [
    "AccessToken",
    "AccessTokenClaims",
    "AccountLockedError",
    "Authenticator",
    "CurrentUser",
    "CurrentUserResolver",
    "LoginRequest",
    "LoginTenantResolver",
    "LoginThrottle",
    "PrincipalResolver",
    "RefreshIssuer",
    "RefreshRotation",
    "RefreshRotator",
    "TOKEN_AUDIENCE",
    "TOKEN_ISSUER",
    "TokenRevoker",
    "TokenValidator",
    "TokenVersionResolver",
    "build_get_principal",
    "build_login_module",
    "build_login_router",
    "build_me_module",
    "build_me_router",
    "clear_refresh_cookie",
    "create_access_token",
    "decode_access_token",
    "generate_refresh_token",
    "get_principal",
    "hash_password",
    "refresh_token_digest",
    "set_refresh_cookie",
    "tenant_from_bearer",
    "verify_password",
    "verify_password_dummy",
]
