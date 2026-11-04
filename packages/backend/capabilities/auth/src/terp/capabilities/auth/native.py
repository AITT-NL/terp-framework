"""Native clients: the refresh token in the body, on routes that refuse a browser (ADR 0195).

ADR 0054 carries the refresh token in an ``HttpOnly; SameSite=Strict`` cookie, and every one
of those properties is a browser property. To a native client (an app on a phone) a
``Set-Cookie`` is just a header, and where its HTTP stack keeps a cookie store at all, that
store is ordinary application data rather than the operating system's keychain or keystore,
which is where a credential that lives for weeks belongs.

So an app that declares :class:`NativeClients` gets two routes of its own,
``/native/login`` and ``/native/refresh``, that answer with the refresh token in the JSON
body. They run the same family, rotation and reuse detection as the cookie routes, through
the same seams, and they refuse a browser outright: :func:`refuse_browser` turns away any
request carrying ``Origin``, a ``Sec-Fetch-*`` header or the refresh cookie, so script in a
page can never be handed a token it could read.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import APIRouter, Request
from sqlmodel import Session

from terp.core import (
    AuthenticationError,
    PermissionDeniedError,
    Policy,
    Principal,
    SessionDep,
    no_idempotency,
    operation,
    route_policy,
    settings,
)

from terp.capabilities.auth.operations import AUTH_NATIVE_LOGIN, AUTH_NATIVE_REFRESH
from terp.capabilities.auth.refresh import RefreshRotation
from terp.capabilities.auth.schemas import LoginRequest, NativeRefreshRequest, NativeSession
from terp.capabilities.auth.seams import RefreshIssuer

#: The sign-in steps ``/login`` takes, handed over so the native route takes exactly them.
SignIn = Callable[[Request, LoginRequest, Session], tuple[Principal, tuple[str, ...]]]

#: What a browser attaches and page script can neither remove nor forge: ``Origin`` on every
#: ``POST``, and the ``Sec-Fetch-*`` family on every request over HTTPS. They are forbidden
#: header names in the Fetch standard, so a request that carries none of them did not come
#: from script running in a page.
_BROWSER_HEADERS = ("origin", "sec-fetch-site", "sec-fetch-mode", "sec-fetch-dest", "sec-fetch-user")


class BrowserOnNativeRouteError(PermissionDeniedError):
    """403 — a native-client route was called from a browser, which uses the cookie routes."""

    code = "native_client_only"
    default_message = (
        "This sign-in route is for native applications. A browser signs in through the "
        "standard routes, which keep the session in a cookie page script cannot read."
    )


@dataclass(frozen=True)
class NativeClients:
    """The declaration that turns the native routes on, with the reason this app needs them.

    Off by default: an app that does not declare it mounts nothing new, and its routes, its
    contract and its authority baseline are unchanged. The reason is required for the same
    reason ``Policy.public_write`` requires one: the routes hand out a long-lived credential
    in a body, and the decision to offer that is one a reviewer should be able to read.
    """

    reason: str

    def __post_init__(self) -> None:
        if not self.reason or not self.reason.strip():
            raise ValueError(
                "NativeClients(reason=...) requires a non-empty justification: the native "
                "routes return the refresh token in the response body (ADR 0195)."
            )


def refuse_browser(request: Request) -> None:
    """Raise :class:`BrowserOnNativeRouteError` for a request with any browser provenance.

    Checked before any credential is read. The refresh cookie counts as provenance too: a
    request presenting the cookie and a body token is refused rather than resolved, so
    there is never a question of which carrier wins.
    """
    present = [name for name in _BROWSER_HEADERS if name in request.headers]
    if present or settings.REFRESH_COOKIE_NAME in request.cookies:
        raise BrowserOnNativeRouteError(
            log_context={
                "browser_headers": present,
                "refresh_cookie": settings.REFRESH_COOKIE_NAME in request.cookies,
            }
        )


def add_native_routes(
    router: APIRouter,
    *,
    sign_in: SignIn,
    mint: Callable[..., tuple[str, int]],
    issue: RefreshIssuer,
    rotate: Callable[[Session, str], RefreshRotation | None],
    resolve: Callable[[Session, uuid.UUID], Principal | None],
) -> None:
    """Mount ``POST /native/login`` and ``POST /native/refresh`` on the login *router*.

    The steps are the cookie routes' own, handed in: *sign_in* is ``/login``'s credential
    check, *mint* its access-token minting, and *issue* / *rotate* / *resolve* the same
    refresh seams ``/login`` and ``/refresh`` call. Only the carrier differs, and the browser
    refusal comes first on both routes.
    """

    @router.post("/native/login", response_model=NativeSession)
    @no_idempotency
    @route_policy(
        Policy.public_write(reason="a native client has no token yet; this route is how it gets one")
    )
    @operation(AUTH_NATIVE_LOGIN)
    def native_login(request: Request, credentials: LoginRequest, session: SessionDep) -> NativeSession:
        # Browser provenance is refused before the password is read: a page may never be
        # handed a refresh token its script could read. Then the very steps /login takes,
        # and a fresh family whose first token leaves in the body.
        refuse_browser(request)
        principal, methods = sign_in(request, credentials, session)
        access_token, token_version = mint(session, principal, amr=methods)
        return NativeSession(
            access_token=access_token,
            refresh_token=issue(session, principal.id, token_version=token_version),
        )

    @router.post("/native/refresh", response_model=NativeSession)
    @no_idempotency
    @route_policy(
        Policy.public_write(
            reason="the refresh token in the body is the credential; there is no bearer to gate on"
        )
    )
    @operation(AUTH_NATIVE_REFRESH)
    def native_refresh(
        request: Request, presented: NativeRefreshRequest, session: SessionDep
    ) -> NativeSession:
        # The same rotation /refresh runs: single use, reuse detection that revokes the whole
        # family, and the subject re-checked as active before anything is minted.
        refuse_browser(request)
        rotation = rotate(session, presented.refresh_token)
        if rotation is None:
            raise AuthenticationError()
        principal = resolve(session, rotation.user_id)
        if principal is None:
            raise AuthenticationError()
        # The family carries the epoch it was issued under, and the mint checks the one it
        # resolves now: an intervening revocation refuses the pair (ADR 0193).
        access_token, token_version = mint(session, principal)
        if rotation.token_version is None or rotation.token_version != token_version:
            raise AuthenticationError()
        return NativeSession(access_token=access_token, refresh_token=rotation.token)


__all__ = ["BrowserOnNativeRouteError", "NativeClients", "SignIn", "add_native_routes", "refuse_browser"]
