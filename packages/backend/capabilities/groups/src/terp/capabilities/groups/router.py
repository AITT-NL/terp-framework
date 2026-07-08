"""Admin ``groups`` router + the discoverable ``ModuleSpec``.

**Admin-only** (``Policy`` requires ``ADMIN``): managing who belongs to which
permission-bundling group is itself a privileged action, exactly like managing
grants. Exposed as ``module`` so the kernel's entry-point discovery mounts it at
``/api/v1/groups`` with no composition-root edit.

Granting a permission *to a group* is not done here — it is an ordinary access
grant (``POST /api/v1/access/grants``) whose ``subject_id`` is the group's id;
this router manages the groups and their memberships.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from terp.core import ModuleSpec, Page, PaginationDep, Policy, Roles, SessionDep

from terp.capabilities.groups.models import Group
from terp.capabilities.groups.schemas import (
    GroupCreate,
    GroupMemberAdd,
    GroupMemberRead,
    GroupRead,
    GroupUpdate,
)
from terp.capabilities.groups.service import GroupsService

router = APIRouter(tags=["groups"])
_service = GroupsService()


def _read(group: Group, member_count: int) -> GroupRead:
    return GroupRead(
        id=group.id,
        name=group.name,
        description=group.description,
        member_count=member_count,
        version=group.version,
        created_at=group.created_at,
        updated_at=group.updated_at,
    )


@router.get("/", response_model=Page[GroupRead])
def list_groups(session: SessionDep, pagination: PaginationDep) -> Page[GroupRead]:
    rows, total = _service.list(session, skip=pagination.skip, limit=pagination.limit)
    counts = _service.member_counts(session, [row.id for row in rows])
    return Page[GroupRead].of(
        [_read(row, counts.get(row.id, 0)) for row in rows], total, pagination
    )


@router.post("/", response_model=GroupRead, status_code=201)
def create_group(payload: GroupCreate, session: SessionDep) -> GroupRead:
    return _read(_service.create(session, payload), 0)


@router.get("/{group_id}", response_model=GroupRead)
def get_group(group_id: uuid.UUID, session: SessionDep) -> GroupRead:
    group = _service.get(session, group_id)
    counts = _service.member_counts(session, [group.id])
    return _read(group, counts.get(group.id, 0))


@router.patch("/{group_id}", response_model=GroupRead)
def update_group(
    group_id: uuid.UUID, payload: GroupUpdate, session: SessionDep
) -> GroupRead:
    group = _service.update(session, group_id, payload)
    counts = _service.member_counts(session, [group.id])
    return _read(group, counts.get(group.id, 0))


@router.delete("/{group_id}", status_code=204)
def delete_group(group_id: uuid.UUID, session: SessionDep) -> None:
    _service.delete(session, group_id)


@router.get("/{group_id}/members", response_model=Page[GroupMemberRead])
def list_members(
    group_id: uuid.UUID, session: SessionDep, pagination: PaginationDep
) -> Page[GroupMemberRead]:
    rows, total = _service.members_for(
        session, group_id, skip=pagination.skip, limit=pagination.limit
    )
    emails = _service.member_emails(session, [row.user_id for row in rows])
    items = [
        GroupMemberRead(
            id=row.id,
            group_id=row.group_id,
            user_id=row.user_id,
            email=emails.get(row.user_id),
            created_at=row.created_at,
        )
        for row in rows
    ]
    return Page[GroupMemberRead].of(items, total, pagination)


@router.post("/{group_id}/members", response_model=GroupMemberRead, status_code=201)
def add_member(
    group_id: uuid.UUID, payload: GroupMemberAdd, session: SessionDep
) -> GroupMemberRead:
    return GroupMemberRead.model_validate(
        _service.add_member(session, group_id, payload.user_id)
    )


@router.delete("/{group_id}/members/{user_id}", status_code=204)
def remove_member(
    group_id: uuid.UUID, user_id: uuid.UUID, session: SessionDep
) -> None:
    _service.remove_member(session, group_id, user_id)


module = ModuleSpec(
    name="groups",
    router=router,
    policy=Policy(read_role=Roles.ADMIN, write_role=Roles.ADMIN),
)
