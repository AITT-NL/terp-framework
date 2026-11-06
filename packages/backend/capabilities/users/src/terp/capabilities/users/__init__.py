"""terp.capabilities.users — admin user management over the identity store.

Provides a :class:`UsersService` and a **self-registering** admin ``users`` router
(list / get / provision / edit / deactivate / reactivate / reset password). The
kernel discovers ``module`` via the ``terp.capabilities`` entry point and mounts
it at ``/api/v1/users`` with no composition-root edit.

The persisted ``User`` (and ``authenticate``) live in ``terp-cap-identity``; this
capability is the **administration surface** over that store, so there is a single
user table shared with the login path. Every write is audited (it routes through
the ``BaseService`` chokepoint) and passwords are hashed via ``terp-cap-auth``.

Self-service accounts (ADR 0196) are the opt-in other half: ``build_accounts_module`` over a
:class:`SelfService` declaration mounts sign-up, proof of address, password reset and
closing under ``/api/v1/accounts``. It is never discovered: an app builds it, or has none.
"""

from __future__ import annotations

from terp.capabilities.users.account_tokens import AccountTokenService
from terp.capabilities.users.accounts import AccountSignsInElsewhereError, AccountsService
from terp.capabilities.users.accounts_router import build_accounts_module, build_accounts_router
from terp.capabilities.users.operations import (
    ACCOUNTS_CLOSE,
    ACCOUNTS_REQUEST_PASSWORD_RESET,
    ACCOUNTS_RESET_PASSWORD,
    ACCOUNTS_SIGN_UP,
    ACCOUNTS_VERIFY,
    USERS_DEACTIVATE,
    USERS_GET,
    USERS_LIST,
    USERS_OPERATIONS,
    USERS_PROVISION,
    USERS_REACTIVATE,
    USERS_RESET_PASSWORD,
    USERS_UPDATE,
)
from terp.capabilities.users.router import module, router
from terp.capabilities.users.schemas import (
    UserAdminUpdate,
    UserPasswordReset,
    UserProvision,
    UserRead,
)
from terp.capabilities.users.self_service import AccountDeletion, AccountMessages, SelfService
from terp.capabilities.users.service import UsersService

__all__ = [
    "ACCOUNTS_CLOSE",
    "ACCOUNTS_REQUEST_PASSWORD_RESET",
    "ACCOUNTS_RESET_PASSWORD",
    "ACCOUNTS_SIGN_UP",
    "ACCOUNTS_VERIFY",
    "AccountDeletion",
    "AccountMessages",
    "AccountSignsInElsewhereError",
    "AccountTokenService",
    "AccountsService",
    "SelfService",
    "build_accounts_module",
    "build_accounts_router",
    "USERS_DEACTIVATE",
    "USERS_GET",
    "USERS_LIST",
    "USERS_OPERATIONS",
    "USERS_PROVISION",
    "USERS_REACTIVATE",
    "USERS_RESET_PASSWORD",
    "USERS_UPDATE",
    "UserAdminUpdate",
    "UserPasswordReset",
    "UserProvision",
    "UserRead",
    "UsersService",
    "module",
    "router",
]
