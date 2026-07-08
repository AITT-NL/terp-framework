"""The groups → access bridge: expand a user to the groups they belong to.

Registered into the access capability's subject-expansion seam at package import
(entry-point discovery imports this package to mount the router, so installing
the capability activates group-aware permission checks with no composition-root
edit). From then on ``AccessService.has_permission`` — behind both
``require_permission`` and the kernel guard's ``permission_enforcer`` — checks
grants against the caller *and* the caller's groups.

Membership lookup is one indexed query per check; expansion is flat by design
(groups do not nest — a group id expands to nothing).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlmodel import Session

from terp.capabilities.access import register_subject_expander

from terp.capabilities.groups.service import GroupsService

_service = GroupsService()


def expand_group_memberships(
    session: Session, subject_id: uuid.UUID
) -> Iterable[uuid.UUID]:
    """The ids of every group *subject_id* belongs to (empty for a non-member)."""
    return _service.group_ids_for(session, subject_id)


def register_group_expansion() -> None:
    """Register the membership expander with the access capability (idempotent)."""
    register_subject_expander(expand_group_memberships)


__all__ = ["expand_group_memberships", "register_group_expansion"]
