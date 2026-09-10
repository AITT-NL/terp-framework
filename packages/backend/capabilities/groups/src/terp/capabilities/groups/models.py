"""The persisted group tables — admin-managed sets of users that bundle permissions.

A :class:`Group` is a named collection; a :class:`GroupMember` is a single,
immutable fact: *user ``user_id`` belongs to group ``group_id``*. Groups carry
**permissions, not roles**: granting a permission to a group is an ordinary
access grant whose ``subject_id`` is the group's id (the FK-less ``Grant``
column anticipates exactly this), and the access capability's subject-expansion
seam makes it effective for every member. The kernel role ladder is untouched —
a group never changes anyone's rank.

``user_id`` is an FK-less UUID for the same reason ``Grant.subject_id`` is: this
capability must not import the higher-layer user table it references, so it stays
a leaf. ``group_id`` *is* a real foreign key — both tables live in this package.

The table names are ``user_group`` / ``user_group_member`` (never bare
``group``, a reserved SQL keyword).
"""

from __future__ import annotations

import uuid

from sqlalchemy import UniqueConstraint
from sqlmodel import Field

from terp.core import BaseTable, OnDelete, Ref


class Group(BaseTable, table=True):
    __tablename__ = "user_group"

    name: str = Field(max_length=200, unique=True, index=True)
    description: str = Field(default="", max_length=500)


class GroupMember(BaseTable, table=True):
    __tablename__ = "user_group_member"
    __table_args__ = (
        UniqueConstraint("group_id", "user_id", name="uq_user_group_member_group_user"),
    )

    # The membership's lifecycle is owned by GroupsService, not by the database:
    # deleting a group drains its memberships through the audited chokepoint first,
    # inside the same write unit, so every removal is audited. A database CASCADE
    # would delete the same rows silently and leave the trail with a hole in it, so
    # the declared action is NO_ACTION -- the database takes none, and the service
    # says why (ADR 0133).
    group_id: uuid.UUID = Ref("user_group.id", on_delete=OnDelete.NO_ACTION)
    user_id: uuid.UUID = Field(index=True)
