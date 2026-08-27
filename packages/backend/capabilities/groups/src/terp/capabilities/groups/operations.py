"""Operation declarations for the ``groups`` capability's admin-only routes.

Each route below declares what it does in plain English (ADR 0102), so a
non-technical reader can see the effect of managing a group or its membership
without having to read HTTP verbs and paths.
"""

from __future__ import annotations

from terp.core import OperationDefinition

GROUPS_LIST = OperationDefinition(id="groups.list_groups", label="List the groups")
GROUPS_CREATE = OperationDefinition(
    id="groups.create_group", label="Create a new group"
)
GROUPS_GET = OperationDefinition(
    id="groups.get_group", label="View a group's details"
)
GROUPS_UPDATE = OperationDefinition(
    id="groups.update_group", label="Change a group's details"
)
GROUPS_DELETE = OperationDefinition(id="groups.delete_group", label="Delete a group")
GROUPS_LIST_MEMBERS = OperationDefinition(
    id="groups.list_members", label="List who belongs to a group"
)
GROUPS_ADD_MEMBER = OperationDefinition(
    id="groups.add_member", label="Add someone to a group"
)
GROUPS_REMOVE_MEMBER = OperationDefinition(
    id="groups.remove_member", label="Remove someone from a group"
)

__all__ = [
    "GROUPS_ADD_MEMBER",
    "GROUPS_CREATE",
    "GROUPS_DELETE",
    "GROUPS_GET",
    "GROUPS_LIST",
    "GROUPS_LIST_MEMBERS",
    "GROUPS_REMOVE_MEMBER",
    "GROUPS_UPDATE",
]
