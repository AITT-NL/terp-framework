"""``tasks`` DTOs."""

from __future__ import annotations

import datetime
import uuid

from sqlmodel import Field

from terp.core import BaseSchema, BaseUpdateSchema


class TaskCreate(BaseSchema):
    title: str = Field(max_length=200)
    status: str = Field(default="open", max_length=20)


class TaskUpdate(BaseUpdateSchema):
    title: str | None = Field(default=None, max_length=200)
    status: str | None = Field(default=None, max_length=20)
    # `version: int` is inherited and required (optimistic concurrency).


class TaskRead(BaseSchema):
    id: uuid.UUID
    title: str
    status: str
    version: int
    created_at: datetime.datetime
    updated_at: datetime.datetime
    created_by_id: uuid.UUID | None
    modified_by_id: uuid.UUID | None
