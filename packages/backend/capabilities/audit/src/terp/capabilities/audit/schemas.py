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


class AuditDayCount(BaseSchema):
    """How many events one calendar day of the requested time zone holds."""

    date: datetime.date
    count: int


class AuditActionCount(BaseSchema):
    """How many events in the window record one action."""

    action: str
    count: int


class AuditTargetCount(BaseSchema):
    """How many events in the window are about records of one type."""

    target_type: str
    count: int


class AuditActivityRead(BaseSchema):
    """The trail's activity over the last ``days`` calendar days, counted in one time zone.

    ``days`` runs oldest first and ends today, with a zero for a day that holds nothing, so a
    chart can draw it as it comes. ``previous_days`` is the same number of days just before,
    for a comparison. The two breakdowns and ``total`` cover ``days`` only, and
    ``by_target_type`` is the most changed types, most first.
    """

    time_zone: str
    days: list[AuditDayCount]
    previous_days: list[AuditDayCount]
    by_action: list[AuditActionCount]
    by_target_type: list[AuditTargetCount]
    total: int


__all__ = [
    "AuditActionCount",
    "AuditActivityRead",
    "AuditDayCount",
    "AuditEventRead",
    "AuditTargetCount",
]
