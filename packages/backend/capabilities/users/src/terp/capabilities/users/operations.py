"""Operation declarations for the ``users`` capability's admin-only routes.

Each route below declares what it does in plain English (ADR 0102), so a
non-technical reader can see the effect of managing a user account — listing,
creating, viewing, editing, disabling, re-enabling, or resetting the password
for one — without having to read HTTP verbs and paths.
"""

from __future__ import annotations

from terp.core import OperationDefinition

USERS_LIST = OperationDefinition(id="users.list_users", label="List every user account")
USERS_PROVISION = OperationDefinition(
    id="users.provision_user", label="Create a new user account"
)
USERS_GET = OperationDefinition(
    id="users.get_user", label="View a user account's details"
)
USERS_UPDATE = OperationDefinition(
    id="users.update_user", label="Change a user account's details"
)
USERS_DEACTIVATE = OperationDefinition(
    id="users.deactivate_user", label="Disable a user account without deleting it"
)
USERS_REACTIVATE = OperationDefinition(
    id="users.reactivate_user", label="Re-enable a disabled user account"
)
USERS_RESET_PASSWORD = OperationDefinition(
    id="users.reset_user_password", label="Set a new password for a user"
)

ACCOUNTS_SIGN_UP = OperationDefinition(
    id="accounts.sign_up", label="Ask to open an account with an email address"
)
ACCOUNTS_VERIFY = OperationDefinition(
    id="accounts.verify", label="Confirm an email address and open the account"
)
ACCOUNTS_REQUEST_PASSWORD_RESET = OperationDefinition(
    id="accounts.request_password_reset", label="Ask for a link to reset a forgotten password"
)
ACCOUNTS_RESET_PASSWORD = OperationDefinition(
    id="accounts.reset_password", label="Choose a new password with a reset link"
)
ACCOUNTS_CLOSE = OperationDefinition(id="accounts.close", label="Close your own account")

#: Every operation this capability's routes declare, in declaration order.
#:
#: An app folds the capability into its :class:`~terp.core.OperationCatalog` by
#: splatting this (``*USERS_OPERATIONS``) rather than naming each constant, so a
#: release that adds a route here cannot refuse a ``STRICT`` app's boot (ADR 0126).
#: Held exhaustive against the router by
#: ``tests/architecture/test_capability_operations.py``.
USERS_OPERATIONS: tuple[OperationDefinition, ...] = (
    USERS_LIST,
    USERS_PROVISION,
    USERS_GET,
    USERS_UPDATE,
    USERS_DEACTIVATE,
    USERS_REACTIVATE,
    USERS_RESET_PASSWORD,
    # Self-service accounts (ADR 0196): declared here even for an app that never builds
    # that module, which is the safe direction for a STRICT catalog (ADR 0126).
    ACCOUNTS_SIGN_UP,
    ACCOUNTS_VERIFY,
    ACCOUNTS_REQUEST_PASSWORD_RESET,
    ACCOUNTS_RESET_PASSWORD,
    ACCOUNTS_CLOSE,
)

__all__ = [
    "ACCOUNTS_CLOSE",
    "ACCOUNTS_REQUEST_PASSWORD_RESET",
    "ACCOUNTS_RESET_PASSWORD",
    "ACCOUNTS_SIGN_UP",
    "ACCOUNTS_VERIFY",
    "USERS_DEACTIVATE",
    "USERS_GET",
    "USERS_LIST",
    "USERS_OPERATIONS",
    "USERS_PROVISION",
    "USERS_REACTIVATE",
    "USERS_RESET_PASSWORD",
    "USERS_UPDATE",
]
