"""The self-service account routes and the module that mounts them (ADR 0196).

``build_accounts_module(SelfService(...))`` mounts five routes under ``/api/v1/accounts``:
four public ones about an address and a token, each declaring its own posture (ADR 0148),
and one authenticated route that closes the caller's own account. Nothing is mounted unless
an app builds it, and building it is refused when the process cannot honour it.
"""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends, Request, Response
from sqlmodel import Field

from terp.core import (
    AuthenticationError,
    BaseSchema,
    InvalidTokenError,
    ModuleSpec,
    Personal,
    Policy,
    Principal,
    RateLimit,
    Roles,
    SessionDep,
    client_ip,
    get_principal,
    is_shared_throttle_store,
    operation,
    route_policy,
)

from terp.capabilities.auth import LoginThrottle
from terp.capabilities.mail import MAIL_SEND, mail_is_configured
from terp.capabilities.users.accounts import AccountsService
from terp.capabilities.users.operations import (
    ACCOUNTS_CLOSE,
    ACCOUNTS_REQUEST_PASSWORD_RESET,
    ACCOUNTS_RESET_PASSWORD,
    ACCOUNTS_SIGN_UP,
    ACCOUNTS_VERIFY,
)
from terp.capabilities.users.self_service import SelfService

_logger = logging.getLogger("terp.capabilities.users.accounts")

#: The throttle key a redemption counts under: a failed redemption is a guess at a token,
#: which has no address to key by, so it is counted per caller.
_REDEEM = "accounts:redeem"


class SignUpRequest(BaseSchema):
    email: str = Personal(max_length=320)
    password: str = Field(max_length=256)


class PasswordResetRequest(BaseSchema):
    email: str = Personal(max_length=320)


class AccountTokenRedemption(BaseSchema):
    """A token from a mail; sealed tokens are a few hundred characters."""

    token: str = Field(min_length=1, max_length=2048)


class PasswordResetConfirmation(BaseSchema):
    token: str = Field(min_length=1, max_length=2048)
    password: str = Field(max_length=256)


class CloseAccountRequest(BaseSchema):
    password: str = Field(max_length=256)


class AccountRequestAccepted(BaseSchema):
    """The one answer a request about an address gets, whatever the address."""

    status: Literal["accepted"] = "accepted"


class AccountOpened(BaseSchema):
    """The account a redeemed sign-up opened; ``active`` is false while it awaits approval."""

    active: bool


def _counted(throttle: LoginThrottle, identifier: str, request: Request) -> None:
    """Back off a caller on *identifier*, every request counting (ADR 0147, never a lockout)."""
    source = client_ip(request)
    throttle.check(identifier, source=source)
    throttle.record_failure(identifier, source=source)


def build_accounts_router(declaration: SelfService) -> APIRouter:
    """The five self-service routes over *declaration*."""
    router = APIRouter(tags=["accounts"])
    throttle = LoginThrottle(store=declaration.throttle_store)
    accounts = AccountsService(declaration)

    @router.post("/sign-up", status_code=202, response_model=AccountRequestAccepted)
    @route_policy(Policy.public_write(reason="a person with no account asks for one"))
    @operation(ACCOUNTS_SIGN_UP)
    def sign_up(request: Request, body: SignUpRequest, session: SessionDep) -> AccountRequestAccepted:
        _counted(throttle, body.email, request)
        accounts.request_sign_up(session, body.email, body.password)
        return AccountRequestAccepted()

    @router.post("/verify", status_code=201, response_model=AccountOpened)
    @route_policy(Policy.public_write(reason="the token mailed to the address is the credential"))
    @operation(ACCOUNTS_VERIFY)
    def verify(request: Request, body: AccountTokenRedemption, session: SessionDep) -> AccountOpened:
        source = client_ip(request)
        throttle.check(_REDEEM, source=source)
        try:
            user = accounts.verify_sign_up(session, body.token)
        except InvalidTokenError:
            throttle.record_failure(_REDEEM, source=source)
            raise
        return AccountOpened(active=user.is_active)

    @router.post("/password-reset", status_code=202, response_model=AccountRequestAccepted)
    @route_policy(Policy.public_write(reason="a person who forgot their password has no session"))
    @operation(ACCOUNTS_REQUEST_PASSWORD_RESET)
    def request_password_reset(
        request: Request, body: PasswordResetRequest, session: SessionDep
    ) -> AccountRequestAccepted:
        _counted(throttle, body.email, request)
        accounts.request_password_reset(session, body.email)
        return AccountRequestAccepted()

    @router.post("/password-reset/confirm", status_code=204)
    @route_policy(Policy.public_write(reason="the token mailed to the address is the credential"))
    @operation(ACCOUNTS_RESET_PASSWORD)
    def reset_password(request: Request, body: PasswordResetConfirmation, session: SessionDep) -> Response:
        source = client_ip(request)
        throttle.check(_REDEEM, source=source)
        try:
            accounts.confirm_password_reset(session, body.token, body.password)
        except InvalidTokenError:
            throttle.record_failure(_REDEEM, source=source)
            raise
        return Response(status_code=204)

    @router.post("/me/close", status_code=204)
    @route_policy(Policy.tiers(read=Roles.VIEWER, write=Roles.VIEWER))
    @operation(ACCOUNTS_CLOSE)
    def close(
        request: Request,
        body: CloseAccountRequest,
        session: SessionDep,
        principal: Principal | None = Depends(get_principal),
    ) -> Response:
        # Any signed-in rank may close its own account, and only its own: the subject is
        # the caller, and the password is asked again so a stolen access token cannot.
        if principal is None:
            raise AuthenticationError()
        identifier, source = f"accounts:close:{principal.id}", client_ip(request)
        throttle.check(identifier, source=source)
        try:
            accounts.close(session, principal, body.password)
        except AuthenticationError:
            throttle.record_failure(identifier, source=source)
            raise
        return Response(status_code=204)

    return router


def build_accounts_module(declaration: SelfService, *, name: str = "accounts") -> ModuleSpec:
    """The self-service accounts ``ModuleSpec``, refused when the process cannot honour it.

    Refused before ``configure_mail`` was called, since every route but one sends mail. It
    declares the ``MAIL_SEND`` job, so a boot whose catalog lacks it is refused. A throttle
    store that is not shared is accepted and said out loud, as the platform does for its own
    (ADR 0036): it is correct for one instance, and wrong only once there are several.
    """
    if not mail_is_configured():
        raise ValueError(
            "self-service accounts send mail: call configure_mail(...) in the composition "
            "root before build_accounts_module (ADR 0196)."
        )
    if not is_shared_throttle_store(declaration.throttle_store):
        _logger.warning(
            "self-service accounts back off PER WORKER in this deployment: the declared "
            "throttle_store is not a shared, multi-instance backend. This is correct for a "
            "single instance; run more than one and each worker keeps its own backoff, so "
            "the requests, and the mail, one address can draw are multiplied by the worker "
            "count. Declare a store marked via terp.core.mark_shared_throttle_store(...) to "
            "make the backoff global (ADR 0196)."
        )
    credentials = RateLimit.credentials()
    return ModuleSpec(
        name=name,
        router=build_accounts_router(declaration),
        policy=Policy.public_write(
            reason="self-service account routes must be reachable by someone with no account"
        ),
        jobs=(MAIL_SEND,),
        # Every route hashes a password or sends mail, so all of them are the credential
        # cost class.
        rate_limit=tuple(
            (path, credentials)
            for path in ("/sign-up", "/verify", "/password-reset", "/password-reset/confirm", "/me/close")
        ),
    )


__all__ = [
    "AccountOpened",
    "AccountRequestAccepted",
    "AccountTokenRedemption",
    "CloseAccountRequest",
    "PasswordResetConfirmation",
    "PasswordResetRequest",
    "SignUpRequest",
    "build_accounts_module",
    "build_accounts_router",
]
