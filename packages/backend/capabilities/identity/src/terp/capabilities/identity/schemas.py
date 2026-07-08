"""Identity DTOs. ``UserRead`` never exposes ``hashed_password``."""

from __future__ import annotations

import datetime
import uuid

from terp.core import BaseSchema


class UserRead(BaseSchema):
    id: uuid.UUID
    email: str
    role: int
    is_active: bool
    version: int
    created_at: datetime.datetime
    updated_at: datetime.datetime
