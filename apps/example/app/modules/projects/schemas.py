"""``projects`` DTOs — compose the kernel schema bases.

``ProjectRead`` surfaces the row's ``tenant_id`` (the caller's *own* tenant) so the
stamping is visible. The registered scope predicate guarantees a caller only ever
reads its own rows, so this is not a cross-tenant leak.
"""

from __future__ import annotations

import datetime
import uuid

from sqlmodel import Field

from terp.core import BaseSchema, BaseUpdateSchema


class ProjectCreate(BaseSchema):
    name: str = Field(max_length=200)


class ProjectUpdate(BaseUpdateSchema):
    name: str | None = Field(default=None, max_length=200)
    # `version: int` is inherited and required (optimistic concurrency).


class ProjectRead(BaseSchema):
    id: uuid.UUID
    name: str
    tenant_id: uuid.UUID
    version: int
    created_at: datetime.datetime
    updated_at: datetime.datetime
