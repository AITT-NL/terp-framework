"""Login + logout router + ``ModuleSpec`` builder for the auth capability.

The capability does **not** own a user store (the identity capability does). The
app supplies an ``authenticate(session, email, password) -> Principal | None``
callback; auth only checks that the credential resolves to a principal and then issues
a token. The login route is mounted with ``Policy.public`` so it is reachable without a
token; the optional logout route revokes the caller's sessions through an app-supplied
seam (auth does not own the store it must write).

Session-management seams (ADR 0031), all optional and app-wired so auth never imports
the store:

* ``token_version_resolver`` signs the subject's **current token epoch** into the issued
  token, so a freshly-minted token is valid against the store (without it, the first
  token issued after any revoking change would be instantly stale);
* ``revoke_sessions`` bumps the caller's epoch on ``POST /logout`` (mounted only when
  wired); and
* ``throttle`` is the per-account login lockout (on by default, ADR 0031 / L3).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import APIRouter, Depends, Request, Response
from sqlmodel import Session

from terp.core import (
    AuthenticationError,
    ModuleSpec,
    Policy,
    Principal,
    SessionDep,
    get_principal,
    settings,
)

from terp.capabilities.auth.refresh import (
    RefreshRotation,
    clear_refresh_cookie,
    set_refresh_cookie,
)
from terp.capabilities.auth.schemas import AccessToken, CurrentUser, LoginRequest
from terp.capabilities.auth.throttle import LoginThrottle
from terp.capabilities.auth.tokens import create_access_token

Authenticator = Callable[[Session, str, str], Principal | None]
LoginTenantResolver = Callable[[Session, Principal], uuid.UUID | None]
# Resolve the subject's current token epoch so login signs it (see module docstring).
TokenVersionResolver = Callable[[Session, Principal], int]
# Revoke (invalidate) a subject's outstanding tokens — the logout write-back, app-wired
# to the store (e.g. ``UsersService.revoke_sessions``) since auth does not own it.
TokenRevoker = Callable[[Session, uuid.UUID], None]
# Refresh-token seams (ADR 0054), app-wired to the identity refresh store so auth never
# imports it. Issue the first token at login; rotate (single-use + reuse-detect) a presented
# token; resolve an ACTIVE subject's principal by id (the /refresh analog of authenticate,
# which needs a password). All three are wired together or not at all.
RefreshIssuer = Callable[[Session, uuid.UUID], str]
RefreshRotator = Callable[[Session, str], RefreshRotation | None]
PrincipalResolver = Callable[[Session, uuid.UUID], Principal | None]
# Resolve the authenticated caller's own identity for ``GET /me`` — app-wired to the
# store (e.g. ``IdentityService.current_user``) so auth never imports where users live
# (symmetric with the authenticate / tenant_resolver / revoke_sessions seams).
CurrentUserResolver = Callable[[Session, Principal], CurrentUser]


def build_login_router(
    authenticate: Authenticator,
    *,
    tenant_resolver: LoginTenantResolver | None = None,
    token_version_resolver: TokenVersionResolver | None = None,
    revoke_sessions: TokenRevoker | None = None,
    throttle: LoginThrottle | None = None,
    refresh_issuer: RefreshIssuer | None = None,
    refresh_rotator: RefreshRotator | None = None,
    principal_resolver: PrincipalResolver | None = None,
    require_refresh: bool = False,
) -> APIRouter:
    """Build a ``/login`` (+ optional ``/logout`` / ``/refresh``) router via *authenticate*.

    When *tenant_resolver* is supplied, the authenticated principal is mapped to a
    tenant and that tenant is signed into the token's ``tenant`` claim — so a
    multi-tenant app issues a tenant-bound token through this one seam (symmetric with
    ``TenantMiddleware``'s ``resolve_tenant``), without the auth capability needing to
    know how a tenant is stored. *token_version_resolver* likewise signs the subject's
    current token epoch (ADR 0031). *throttle* (default: a fresh on-by-default
    :class:`LoginThrottle`) locks an account after repeated failed logins. When
    *revoke_sessions* is supplied, a ``POST /logout`` route is mounted that bumps the
    caller's epoch (idempotent; an unauthenticated call is a no-op).

    Refresh-token rotation (ADR 0054) is opt-in and **all-or-nothing**: supply
    *refresh_issuer* (open a family + mint the first token at login), *refresh_rotator*
    (validate + single-use rotate + reuse-detect), and *principal_resolver* (resolve an
    active subject by id) together — plus *revoke_sessions*, so ``/logout`` revokes the
    family server-side and not just the cookie — to mount ``POST /refresh`` and have
    ``/login`` / ``/logout`` set / clear the httpOnly refresh cookie. Wiring only some of
    the seams, omitting *revoke_sessions*, or passing *require_refresh* without them,
    raises at construction (fail-closed).
    """
    router = APIRouter(tags=["auth"])
    active_throttle = throttle if throttle is not None else LoginThrottle()

    # Refresh rotation is all-or-nothing: a token issued at login that nothing can rotate
    # (or vice versa) is a fail-closed misconfiguration caught here, at construction.
    refresh_enabled = (
        refresh_issuer is not None
        and refresh_rotator is not None
        and principal_resolver is not None
    )
    any_refresh_seam = (
        refresh_issuer is not None
        or refresh_rotator is not None
        or principal_resolver is not None
    )
    if any_refresh_seam and not refresh_enabled:
        raise ValueError(
            "refresh-token rotation is half-wired: refresh_issuer, refresh_rotator, and "
            "principal_resolver must be supplied together (ADR 0054)."
        )
    if refresh_enabled and revoke_sessions is None:
        # Without a server-side revoker, /logout could only drop the browser cookie while
        # every token in the family stayed live in the store — a logout that does not log
        # out. Refuse the half-secure shape at construction (fail-closed).
        raise ValueError(
            "refresh-token rotation requires revoke_sessions: without it a logout clears "
            "the cookie but leaves the refresh-token family live server-side (ADR 0054)."
        )
    if require_refresh and not refresh_enabled:
        raise ValueError(
            "require_refresh=True but the refresh seams are not wired (ADR 0054)."
        )

    def _mint_access_token(session: Session, principal: Principal) -> str:
        tenant = tenant_resolver(session, principal) if tenant_resolver is not None else None
        token_version = (
            token_version_resolver(session, principal)
            if token_version_resolver is not None
            else 0
        )
        return create_access_token(
            subject=principal.id,
            role=principal.role,
            tenant=tenant,
            token_version=token_version,
        )

    @router.post("/login", response_model=AccessToken)
    def login(
        credentials: LoginRequest, session: SessionDep, response: Response
    ) -> AccessToken:
        active_throttle.check(credentials.email)
        principal = authenticate(session, credentials.email, credentials.password)
        if principal is None:
            active_throttle.record_failure(credentials.email)
            raise AuthenticationError()
        active_throttle.record_success(credentials.email)
        token = _mint_access_token(session, principal)
        if refresh_issuer is not None:
            # Open a fresh refresh-token family and set its httpOnly cookie beside the
            # bearer, so the session survives a reload and can outlive the access TTL.
            set_refresh_cookie(response, refresh_issuer(session, principal.id))
        return AccessToken(access_token=token)

    if refresh_rotator is not None and principal_resolver is not None:
        rotate_token = refresh_rotator
        resolve_principal = principal_resolver

        @router.post("/refresh", response_model=AccessToken)
        def refresh(
            request: Request, session: SessionDep, response: Response
        ) -> AccessToken:
            # The refresh cookie is the credential here (no bearer): rotate it (single-use +
            # reuse-detection), re-check the subject is still active, then mint a fresh
            # access token and set the rotated cookie. Any failure is a clean 401.
            raw = request.cookies.get(settings.REFRESH_COOKIE_NAME)
            if raw is None:
                raise AuthenticationError()
            rotation = rotate_token(session, raw)
            if rotation is None:
                raise AuthenticationError()
            principal = resolve_principal(session, rotation.user_id)
            if principal is None:
                raise AuthenticationError()
            token = _mint_access_token(session, principal)
            set_refresh_cookie(response, rotation.token)
            return AccessToken(access_token=token)

    if revoke_sessions is not None or refresh_enabled:

        @router.post("/logout", status_code=204)
        def logout(
            session: SessionDep,
            principal: Principal | None = Depends(get_principal),
        ) -> Response:
            # Logout is idempotent: with no (or an already-revoked) token there is nothing
            # to invalidate. Otherwise bump the caller's epoch (the wired revoke also kills
            # the refresh families), and always drop the refresh cookie.
            if principal is not None and revoke_sessions is not None:
                revoke_sessions(session, principal.id)
            response = Response(status_code=204)
            if refresh_enabled:
                clear_refresh_cookie(response)
            return response

    return router


def build_login_module(
    authenticate: Authenticator,
    *,
    name: str = "auth",
    tenant_resolver: LoginTenantResolver | None = None,
    token_version_resolver: TokenVersionResolver | None = None,
    revoke_sessions: TokenRevoker | None = None,
    throttle: LoginThrottle | None = None,
    refresh_issuer: RefreshIssuer | None = None,
    refresh_rotator: RefreshRotator | None = None,
    principal_resolver: PrincipalResolver | None = None,
    require_refresh: bool = False,
) -> ModuleSpec:
    """Build the auth ``ModuleSpec`` (public login + optional logout / refresh endpoints).

    When the refresh seams are wired, the configured refresh-cookie path must match where
    this module is mounted (``/api/v1/<name>``) — a path-scoped cookie the browser never
    sends to ``/refresh`` would make refresh silently never work, so the mismatch is
    refused here, at construction (fail-closed).
    """
    refresh_enabled = (
        refresh_issuer is not None
        and refresh_rotator is not None
        and principal_resolver is not None
    )
    mount_prefix = f"/api/v1/{name}"
    if refresh_enabled and settings.REFRESH_COOKIE_PATH != mount_prefix:
        raise ValueError(
            f"REFRESH_COOKIE_PATH ({settings.REFRESH_COOKIE_PATH!r}) does not match this "
            f"module's mount prefix ({mount_prefix!r}); the browser would never send the "
            "refresh cookie to /refresh (ADR 0054)."
        )
    return ModuleSpec(
        name=name,
        router=build_login_router(
            authenticate,
            tenant_resolver=tenant_resolver,
            token_version_resolver=token_version_resolver,
            revoke_sessions=revoke_sessions,
            throttle=throttle,
            refresh_issuer=refresh_issuer,
            refresh_rotator=refresh_rotator,
            principal_resolver=principal_resolver,
            require_refresh=require_refresh,
        ),
        policy=Policy.public_write(
            reason="authentication endpoints must be reachable without a token"
        ),
    )


def build_me_router(resolve_current_user: CurrentUserResolver) -> APIRouter:
    """Build the ``GET /me`` (who-am-I) router via the *resolve_current_user* seam.

    The route is **self-scoped**: it reports only the authenticated caller's own identity
    (read from ``principal.id``), so it takes no id parameter and cannot be turned into a
    read of another subject. Mounted behind ``Policy.default()`` (any authenticated
    caller), it answers through the wired principal provider — the revocable one in the
    bundled stack — so a deactivated / demoted / re-tenanted token is already rejected and
    the response reflects the live record rather than stale token claims.
    """
    router = APIRouter(tags=["auth"])

    @router.get("/", response_model=CurrentUser)
    def me(
        session: SessionDep,
        principal: Principal | None = Depends(get_principal),
    ) -> CurrentUser:
        # The module guard authorizes against Policy.default() (rejecting anonymous)
        # before this handler runs; the explicit check keeps the router correct — a clean
        # 401, never an AttributeError — even if it were ever mounted without that guard.
        if principal is None:
            raise AuthenticationError()
        return resolve_current_user(session, principal)

    return router


def build_me_module(
    resolve_current_user: CurrentUserResolver, *, name: str = "me"
) -> ModuleSpec:
    """Build the who-am-I ``ModuleSpec`` (``GET /api/v1/me``, any authenticated caller)."""
    return ModuleSpec(
        name=name,
        router=build_me_router(resolve_current_user),
        policy=Policy.default(),
    )


__all__ = [
    "Authenticator",
    "CurrentUserResolver",
    "LoginTenantResolver",
    "PrincipalResolver",
    "RefreshIssuer",
    "RefreshRotator",
    "TokenRevoker",
    "TokenVersionResolver",
    "build_login_module",
    "build_login_router",
    "build_me_module",
    "build_me_router",
]
