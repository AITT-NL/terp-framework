"""Read DTOs for the audit log. The log is append-only — there is no write surface."""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from terp.core import BaseSchema


class AuditEventRead(BaseSchema):
    id: uuid.UUID
    action: str
    target_type: str
    target_id: str
    actor_id: uuid.UUID | None
    request_id: str | None
    payload: dict[str, Any] | None
    created_at: datetime.datetime


__all__ = ["AuditEventRead"]
