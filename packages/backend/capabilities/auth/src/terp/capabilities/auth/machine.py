"""The client-credentials grant: a machine signs in with its own secret (ADR 0088).

Mounted beside ``/login`` when an app wires a service-account store. It takes the login
router's throttle and its minting step as parameters, the way the native routes do, so the
password and machine grants cannot drift apart in how they back off or what they sign.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Request

from terp.core import (
    AuthenticationError,
    Policy,
    SessionDep,
    client_ip,
    no_idempotency,
    operation,
    route_policy,
)

from terp.capabilities.auth.operations import AUTH_TOKEN
from terp.capabilities.auth.schemas import AccessToken, ClientCredentialsRequest
from terp.capabilities.auth.seams import ClientAuthenticator
from terp.capabilities.auth.throttle import LoginThrottle


def add_token_route(
    router: APIRouter,
    *,
    verify_client: ClientAuthenticator,
    throttle: LoginThrottle,
    mint: Callable[..., tuple[str, int]],
) -> None:
    """Mount ``POST /token`` on the login *router*."""

    @router.post("/token", response_model=AccessToken)
    @no_idempotency
    @route_policy(Policy.public_write(reason="a caller has no token yet; this route is how they get one"))
    @operation(AUTH_TOKEN)
    def token(
        request: Request,
        credentials: ClientCredentialsRequest,
        session: SessionDep,
    ) -> AccessToken:
        # The non-interactive grant (ADR 0088). This carried no throttle at all,
        # for a reason that was sound about lockouts and wrong about throttling:
        # a *lockout* keyed on a client id would let anyone who learns one take an
        # integration offline at will. Backoff has no such property — it is keyed
        # by (client id, caller), so a stranger failing against an integration's id
        # slows only themselves, and the integration authenticating from its own
        # host is untouched.
        #
        # What that left behind was worse than the brute-force question: every
        # attempt ran a memory-hard KDF — the real verification on a wrong secret,
        # a dummy one on an unknown client id so the miss path costs the same and
        # cannot be used as an oracle. An unauthenticated endpoint that hashes
        # before it throttles is a way to spend the server's CPU and memory that
        # needs no valid credential at all.
        #
        # No refresh cookie either — a machine holds a durable secret and simply
        # re-authenticates, so there is nothing a refresh token would buy except
        # another long-lived credential to leak.
        source = client_ip(request)
        throttle.check(credentials.client_id, source=source)
        principal = verify_client(session, credentials.client_id, credentials.client_secret)
        if principal is None:
            throttle.record_failure(credentials.client_id, source=source)
            raise AuthenticationError()
        throttle.record_success(credentials.client_id, source=source)
        access_token, _ = mint(session, principal)
        return AccessToken(access_token=access_token)


__all__ = ["add_token_route"]
