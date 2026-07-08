"""``notes`` DTOs — compose the kernel schema bases.

``NoteUpdate`` inherits :class:`terp.core.BaseUpdateSchema`, so the client must
echo the OCC ``version`` it last read.
"""

from __future__ import annotations

import datetime
import uuid

from sqlmodel import Field

from terp.core import BaseSchema, BaseUpdateSchema


class NoteCreate(BaseSchema):
    title: str = Field(max_length=200)
    body: str = Field(default="", max_length=10_000)


class NoteUpdate(BaseUpdateSchema):
    title: str | None = Field(default=None, max_length=200)
    body: str | None = Field(default=None, max_length=10_000)
    # `version: int` is inherited and required (optimistic concurrency).


class NoteRead(BaseSchema):
    id: uuid.UUID
    title: str
    body: str
    version: int
    created_at: datetime.datetime
    updated_at: datetime.datetime
    created_by_id: uuid.UUID | None
    modified_by_id: uuid.UUID | None
