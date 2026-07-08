"""Access DTOs. Grants are immutable, so there is no public ``*Update`` surface."""

from __future__ import annotations

import datetime
import uuid

from sqlmodel import Field

from terp.core import BaseSchema, BaseUpdateSchema


class GrantCreate(BaseSchema):
    subject_id: uuid.UUID
    permission: str = Field(max_length=128)


class GrantUpdate(BaseUpdateSchema):
    """Grants are immutable (subject + permission) — nothing is updatable.

    Present only to satisfy ``BaseService``'s ``UpdateT`` type parameter; the
    admin router never exposes an update route.
    """


class GrantRead(BaseSchema):
    id: uuid.UUID
    subject_id: uuid.UUID
    permission: str
    version: int
    created_at: datetime.datetime
    updated_at: datetime.datetime
