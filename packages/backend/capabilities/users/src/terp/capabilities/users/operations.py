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

__all__ = [
    "USERS_DEACTIVATE",
    "USERS_GET",
    "USERS_LIST",
    "USERS_PROVISION",
    "USERS_REACTIVATE",
    "USERS_RESET_PASSWORD",
    "USERS_UPDATE",
]
