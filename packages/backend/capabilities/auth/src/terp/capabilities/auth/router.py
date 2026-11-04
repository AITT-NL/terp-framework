"""Login + logout router + ``ModuleSpec`` builder for the auth capability.

The capability does **not** own a user store (the identity capability does). The
app supplies an ``authenticate(session, email, password) -> Principal | None``
callback; auth only checks that the credential resolves to a principal and then issues
a token. The login route is mounted with ``Policy.public`` so it is reachable without a
token; the optional logout route revokes the caller's sessions through an app-supplied
seam (auth does not own the store it must write).

Session-management seams (ADR 0031), all optional and app-wired so auth never imports
the store:

* ``token_version_resolver`` checks the **captured token epoch** against the current
  store. Epoch-aware authenticators return ``AuthenticatedPrincipal`` so the role and
  epoch come from one snapshot; an intervening revoking change refuses the mint;
* ``revoke_sessions`` bumps the caller's epoch on ``POST /logout`` (mounted only when
  wired); and
* ``throttle`` is the failed-credential backoff (on by default, ADR 0031 / L3), keyed
  by ``(identifier, caller address)`` and applied to ``/login`` **and** ``/token``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlmodel import Session

from terp.core import (
    AuthenticationError,
    ModuleSpec,
    Policy,
    Principal,
    RateLimit,
    SessionDep,
    client_ip,
    get_principal,
    operation,
    no_idempotency,
    route_policy,
    settings,
)

from terp.capabilities.auth.machine import add_token_route
from terp.capabilities.auth.native import NativeClients, add_native_routes
from terp.capabilities.auth.operations import (
    AUTH_LOGIN,
    AUTH_LOGOUT,
    AUTH_ME,
    AUTH_REFRESH,
    AUTH_TOKEN,
)
from terp.capabilities.auth.refresh import (
    clear_refresh_cookie,
    set_refresh_cookie,
)
from terp.capabilities.auth.schemas import (
    AccessToken,
    ClientCredentialsRequest,
    CurrentUser,
    LoginRequest,
)
from terp.capabilities.auth.second_factor import MfaRequiredError, SecondFactor
from terp.capabilities.auth.seams import (
    Authenticator,
    ClientAuthenticator,
    CurrentUserResolver,
    LoginTenantResolver,
    PrincipalResolver,
    RefreshIssuer,
    RefreshRevoker,
    RefreshRotator,
    ServiceTokenVersionResolver,
    TokenRevoker,
    TokenVersionResolver,
)
from terp.capabilities.auth.snapshot import resolve_token_version
from terp.capabilities.auth.throttle import LoginThrottle
from terp.capabilities.auth.tokens import SubjectKind, create_access_token



def build_login_router(
    authenticate: Authenticator,
    *,
    tenant_resolver: LoginTenantResolver | None = None,
    token_version_resolver: TokenVersionResolver | None = None,
    revoke_sessions: TokenRevoker | None = None,
    throttle: LoginThrottle | None = None,
    refresh_issuer: RefreshIssuer | None = None,
    refresh_rotator: RefreshRotator | None = None,
    refresh_revoker: RefreshRevoker | None = None,
    principal_resolver: PrincipalResolver | None = None,
    authenticate_client: ClientAuthenticator | None = None,
    service_token_version_resolver: ServiceTokenVersionResolver | None = None,
    second_factor: SecondFactor | None = None,
    require_refresh: bool = False,
    native_clients: NativeClients | None = None,
) -> APIRouter:
    """Build a ``/login`` (+ optional ``/logout`` / ``/refresh`` / ``/token``) router.

    Built via *authenticate*.

    When *tenant_resolver* is supplied, the authenticated principal is mapped to a
    tenant and that tenant is signed into the token's ``tenant`` claim — so a
    multi-tenant app issues a tenant-bound token through this one seam (symmetric with
    ``TenantMiddleware``'s ``resolve_tenant``), without the auth capability needing to
    know how a tenant is stored. *token_version_resolver* likewise signs the subject's
    current token epoch (ADR 0031). *throttle* (default: a fresh on-by-default
    :class:`LoginThrottle`) locks an account after repeated failed logins. When
    *revoke_sessions* is supplied, a ``POST /logout`` route is mounted that bumps the
    caller's epoch. Cookie-only logout independently revokes the presented family.

    Refresh-token rotation (ADR 0054) is opt-in and **all-or-nothing**: supply
    *refresh_issuer* (open a family + mint the first token at login), *refresh_rotator*
    (validate + single-use rotate + reuse-detect), and *principal_resolver* (resolve an
    active subject by id) together — plus *revoke_sessions* and *refresh_revoker*, so
    ``/logout`` revokes both bearer and cookie credentials server-side — to mount ``POST /refresh`` and have
    ``/login`` / ``/logout`` set / clear the httpOnly refresh cookie. Wiring only some of
    the seams, omitting *revoke_sessions*, or passing *require_refresh* without them,
    raises at construction (fail-closed).

    Client credentials (ADR 0088) are opt-in the same way: supply *authenticate_client*
    and *service_token_version_resolver* together to mount ``POST /token``, the
    non-interactive grant a machine integration uses instead of borrowing a person's
    login. Supplying only one raises here — a machine token minted without the account's
    current epoch would be signed stale and rejected by the very next request, which is
    a failure mode nobody diagnoses correctly under time pressure.

    Native clients (ADR 0195) are opt-in with a reason: *native_clients* mounts
    ``POST /native/login``, ``/native/refresh`` and ``/native/logout``, which carry the refresh
    token in the JSON body for an app with no browser to hold a cookie, run the same family, rotation and
    reuse detection through the same seams, and refuse any request with browser provenance.
    They need the refresh seams, and declaring them without the seams raises here.
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
    if refresh_enabled and refresh_revoker is None:
        raise ValueError(
            "refresh-token rotation requires refresh_revoker: cookie-only logout must "
            "revoke the presented family without issuing another token."
        )
    if refresh_revoker is not None and not refresh_enabled:
        raise ValueError("refresh_revoker requires the complete refresh-token seams.")
    if require_refresh and not refresh_enabled:
        raise ValueError(
            "require_refresh=True but the refresh seams are not wired (ADR 0054)."
        )
    if native_clients is not None and not refresh_enabled:
        raise ValueError(
            "native clients need the refresh seams: /native/refresh rotates a token in the "
            "same refresh store /refresh does, so declaring NativeClients without "
            "refresh_issuer, refresh_rotator and principal_resolver is refused (ADR 0195)."
        )
    if (authenticate_client is None) != (service_token_version_resolver is None):
        raise ValueError(
            "client credentials are half-wired: authenticate_client and "
            "service_token_version_resolver must be supplied together, or a machine "
            "token would be minted at a stale token epoch (ADR 0088)."
        )

    def _mint_access_token(
        session: Session, principal: Principal, *, amr: tuple[str, ...] = ()
    ) -> tuple[str, int]:
        tenant = tenant_resolver(session, principal) if tenant_resolver is not None else None
        kind = SubjectKind(principal.kind)
        resolver = (
            service_token_version_resolver
            if kind is SubjectKind.SERVICE
            else token_version_resolver
        )
        token_version = resolve_token_version(session, principal, resolver)
        return create_access_token(
            subject=principal.id,
            role=principal.role,
            tenant=tenant,
            token_version=token_version,
            kind=kind,
            amr=amr,
        ), token_version

    def _sign_in(
        request: Request, credentials: LoginRequest, session: Session
    ) -> tuple[Principal, tuple[str, ...]]:
        """The steps every password sign-in takes, browser or native, in one place.

        ``/login`` and ``/native/login`` differ only in how the session leaves the server,
        so the throttle, the credential check and the second factor are this one function
        and cannot drift apart. Returns the principal and the methods it proved.
        """
        # The caller's address is half the throttle key. Without it the backoff is a
        # property of the account, which is what let one caller spend it on another.
        source = client_ip(request)
        active_throttle.check(credentials.email, source=source)
        principal = authenticate(session, credentials.email, credentials.password)
        if principal is None:
            active_throttle.record_failure(credentials.email, source=source)
            raise AuthenticationError()
        # Checked AFTER the password and BEFORE success is recorded: a wrong code is
        # a failed attempt, and recording success first would clear the throttle for
        # a caller who has not finished authenticating.
        methods: tuple[str, ...] = ("pwd",)
        if second_factor is not None and second_factor.is_enrolled(session, principal.id):
            if not credentials.mfa_code:
                active_throttle.record_failure(credentials.email, source=source)
                raise MfaRequiredError()
            if not second_factor.verify(session, principal.id, credentials.mfa_code):
                active_throttle.record_failure(credentials.email, source=source)
                raise AuthenticationError()
            methods = ("pwd", "otp")
        active_throttle.record_success(credentials.email, source=source)
        return principal, methods

    @router.post("/login", response_model=AccessToken)
    @no_idempotency
    @route_policy(Policy.public_write(reason="a caller has no token yet; this route is how they get one"))
    @operation(AUTH_LOGIN)
    def login(
        request: Request,
        credentials: LoginRequest,
        session: SessionDep,
        response: Response,
    ) -> AccessToken:
        principal, methods = _sign_in(request, credentials, session)
        token, token_version = _mint_access_token(session, principal, amr=methods)
        if refresh_issuer is not None:
            # Open a fresh refresh-token family and set its httpOnly cookie beside the
            # bearer, so the session survives a reload and can outlive the access TTL.
            set_refresh_cookie(
                response,
                refresh_issuer(session, principal.id, token_version=token_version),
            )
        return AccessToken(access_token=token)

    if authenticate_client is not None:
        add_token_route(
            router, verify_client=authenticate_client, throttle=active_throttle, mint=_mint_access_token
        )

    if refresh_rotator is not None and principal_resolver is not None:
        rotate_token = refresh_rotator
        resolve_principal = principal_resolver

        @router.post("/refresh", response_model=AccessToken)
        @no_idempotency
        @route_policy(
            Policy.public_write(
                reason="the refresh cookie is the credential; there is no bearer to gate on"
            )
        )
        @operation(AUTH_REFRESH)
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
            token, token_version = _mint_access_token(session, principal)
            if rotation.token_version is None or rotation.token_version != token_version:
                raise AuthenticationError()
            set_refresh_cookie(response, rotation.token)
            return AccessToken(access_token=token)

    if (
        native_clients is not None
        and refresh_issuer is not None
        and refresh_rotator is not None
        and principal_resolver is not None
        and refresh_revoker is not None
    ):
        add_native_routes(
            router,
            sign_in=_sign_in,
            mint=_mint_access_token,
            issue=refresh_issuer,
            rotate=refresh_rotator,
            resolve=principal_resolver,
            revoke=refresh_revoker,
        )

    if revoke_sessions is not None or refresh_enabled:

        @router.post("/logout", status_code=204)
        @route_policy(
            Policy.public_write(
                reason="logout is idempotent and must clear a cookie even for a caller "
                "whose token has already expired"
            )
        )
        @operation(AUTH_LOGOUT)
        def logout(
            request: Request,
            session: SessionDep,
            principal: Principal | None = Depends(get_principal),
        ) -> Response:
            # Logout is idempotent and clears the cookie even if it was already revoked.
            # A cookie still identifies its family after its bearer has gone, or
            # after a racing tab spent that particular token. Revoke that family
            # directly: rotating just to discover its subject would mint a successor
            # during logout and miss spent/expired tokens with a live successor.
            raw = request.cookies.get(settings.REFRESH_COOKIE_NAME)
            if raw is not None and refresh_revoker is not None:
                refresh_revoker(session, raw)
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
    refresh_revoker: RefreshRevoker | None = None,
    principal_resolver: PrincipalResolver | None = None,
    authenticate_client: ClientAuthenticator | None = None,
    service_token_version_resolver: ServiceTokenVersionResolver | None = None,
    second_factor: SecondFactor | None = None,
    require_refresh: bool = False,
    native_clients: NativeClients | None = None,
) -> ModuleSpec:
    """Build the auth ``ModuleSpec`` (public login + optional logout / refresh / token).

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
            refresh_revoker=refresh_revoker,
            principal_resolver=principal_resolver,
            authenticate_client=authenticate_client,
            service_token_version_resolver=service_token_version_resolver,
            second_factor=second_factor,
            require_refresh=require_refresh,
            native_clients=native_clients,
        ),
        policy=Policy.public_write(
            reason="authentication endpoints must be reachable without a token"
        ),
        # This mount's own caps, so installing the capability is enough and there is no
        # composition-root line to forget (ADR 0138). They are keyed by route, because
        # this mount is not one cost class (ADR 0140): `/login` and `/token` verify a
        # credential, and a credential check is memory-hard ON PURPOSE -- including on
        # the miss paths, because an unknown subject must cost the same as a wrong
        # secret or the timing enumerates accounts. That makes those two the cheapest
        # place on the whole surface to spend the server's CPU, which the app's general
        # limit was never sized against.
        #
        # `/refresh` and `/logout` are deliberately NOT capped here. Neither hashes a
        # password: `/refresh` reads a high-entropy cookie and rotates it, which costs a
        # query, and it is the route `TerpProvider` probes on EVERY mount to restore a
        # session -- so its volume tracks page loads, not login attempts. Capping it at
        # the credential rate throttles ordinary navigation, and behind a shared egress
        # address (one office, one IP) it takes that office offline, which is the exact
        # outcome `RateLimit.credentials()` gives as the reason a per-address lockout
        # cannot exist. They keep the app's general limit, which is still a cap.
        #
        # A deployment that has measured its own login traffic overrides the absolute
        # prefix in SecurityConfig.rate_limit_overrides.
        # `/native/login`, where it is mounted, checks a password exactly as `/login` does, so
        # it is the same cost class and takes the same cap; `/native/refresh` is `/refresh`'s
        # twin and keeps the general limit, for the reason given above.
        rate_limit={
            "/login": RateLimit.credentials(),
            "/token": RateLimit.credentials(),
            **({"/native/login": RateLimit.credentials()} if native_clients is not None else {}),
        },
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
    @operation(AUTH_ME)
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
    "RefreshRevoker",
    "RefreshRotator",
    "TokenRevoker",
    "TokenVersionResolver",
    "build_login_module",
    "build_login_router",
    "build_me_module",
    "build_me_router",
]
