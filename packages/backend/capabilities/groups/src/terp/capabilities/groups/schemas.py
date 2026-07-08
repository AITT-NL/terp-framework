"""Group DTOs — the admin surface's request / response shapes.

``GroupRead`` carries a live ``member_count`` so the admin overview can show
group sizes without N+1 member listings. Memberships are immutable rows
(add / remove, never edited), so there is no member ``*Update`` surface.
"""

from __future__ import annotations

import datetime
import uuid

from sqlmodel import Field

from terp.core import BaseSchema, BaseUpdateSchema


class GroupCreate(BaseSchema):
    name: str = Field(max_length=200)
    description: str = Field(default="", max_length=500)


class GroupUpdate(BaseUpdateSchema):
    name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=500)


class GroupRead(BaseSchema):
    id: uuid.UUID
    name: str
    description: str
    member_count: int
    version: int
    created_at: datetime.datetime
    updated_at: datetime.datetime


class GroupMemberAdd(BaseSchema):
    user_id: uuid.UUID


class GroupMemberRead(BaseSchema):
    id: uuid.UUID
    group_id: uuid.UUID
    user_id: uuid.UUID
    # Resolved from the identity store when the member listing is served (one query
    # per page); None when the account no longer exists (user_id is FK-less).
    email: str | None = None
    created_at: datetime.datetime
