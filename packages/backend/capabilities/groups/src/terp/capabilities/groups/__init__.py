"""terp.capabilities.groups — admin-managed user groups that bundle permissions.

The kernel ``Policy`` guard enforces the coarse role ladder; the access
capability adds per-permission grants. This capability adds the missing
middle: **groups** — named sets of users that hold grants *collectively*:

* persisted :class:`Group` / :class:`GroupMember` tables (flat, no nesting),
* an audited :class:`GroupsService` (CRUD + idempotent membership management;
  deleting a group cascades to its memberships and its grants atomically),
* a **self-registering**, admin-only ``groups`` router at ``/api/v1/groups``,
* the access subject-expansion bridge: importing this package registers
  :func:`~terp.capabilities.groups.expander.expand_group_memberships`, so a
  grant whose subject is a group id is effective for every member — through
  ``require_permission`` and the kernel guard alike, with no call-site changes.

Granting to a group is an ordinary access grant (``subject_id`` = the group's
id). Groups carry permissions, never roles: the single-role ladder (ADR 0004)
is untouched.
"""

from __future__ import annotations

from terp.capabilities.groups.expander import (
    expand_group_memberships,
    register_group_expansion,
)
from terp.capabilities.groups.models import Group, GroupMember
from terp.capabilities.groups.router import module, router
from terp.capabilities.groups.schemas import (
    GroupCreate,
    GroupMemberAdd,
    GroupMemberRead,
    GroupRead,
    GroupUpdate,
)
from terp.capabilities.groups.service import GroupsService

# Importing the capability (entry-point discovery does) activates group-aware
# permission checks; without the import, access behaves exactly as before.
register_group_expansion()

__all__ = [
    "Group",
    "GroupCreate",
    "GroupMember",
    "GroupMemberAdd",
    "GroupMemberRead",
    "GroupRead",
    "GroupUpdate",
    "GroupsService",
    "expand_group_memberships",
    "module",
    "register_group_expansion",
    "router",
]
