"""``journals`` DTOs — compose the kernel schema bases.

``JournalRead`` surfaces the stamped ``owner_id`` so ownership is visible to the
client. A client never *sets* it — the framework stamps it on create — so it is absent
from ``JournalCreate`` / ``JournalUpdate`` (the ``input_schemas_exclude_managed_columns``
rule forbids a managed column on an input schema, closing the over-posting hole where a
caller could otherwise forge ownership).
"""

from __future__ import annotations

import datetime
import uuid

from sqlmodel import Field

from terp.core import BaseSchema, BaseUpdateSchema


class JournalCreate(BaseSchema):
    title: str = Field(max_length=200)
    entry: str = Field(default="", max_length=10_000)
    visibility: str = Field(default="shared", max_length=20)


class JournalUpdate(BaseUpdateSchema):
    title: str | None = Field(default=None, max_length=200)
    entry: str | None = Field(default=None, max_length=10_000)
    visibility: str | None = Field(default=None, max_length=20)
    # `version: int` is inherited and required (optimistic concurrency).


class JournalRead(BaseSchema):
    id: uuid.UUID
    title: str
    entry: str
    visibility: str
    owner_id: uuid.UUID | None
    version: int
    created_at: datetime.datetime
    updated_at: datetime.datetime
