"""Read access to the audit log — one paginated, newest-first query, and its activity per day.

The log is append-only (written by the sink), so this capability exposes only a
read path: a single, bounded list used by the admin router, optionally narrowed to
the one record a screen is about, and the counts a dashboard draws from. The list
mirrors the kernel's pagination contract so the trail is browsed like any other
``Page[T]``.
"""

from __future__ import annotations

import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import case
from sqlmodel import Session, col, func, select

from terp.core import PaginationParams, ValidationFailedError

from terp.capabilities.audit.models import AuditEvent
from terp.capabilities.audit.schemas import (
    AuditActionCount,
    AuditActivityRead,
    AuditDayCount,
    AuditTargetCount,
)

#: The longest window the activity read counts, in days. Each day is one aggregate in a
#: single query, so the bound keeps that query small as well as the response.
ACTIVITY_MAX_DAYS = 90

#: How many record types the activity read ranks. The rest are still in ``total``.
ACTIVITY_TOP_TARGETS = 8


def list_audit_events(
    session: Session,
    *,
    pagination: PaginationParams,
    target_type: str | None = None,
    target_id: str | None = None,
) -> tuple[list[AuditEvent], int]:
    """Return one page of audit events, newest first, with the total count.

    ``target_type`` and ``target_id`` narrow the trail to the record a detail screen is
    about -- both columns are indexed for exactly this read. Either alone narrows too;
    neither returns the whole trail, as before.
    """
    conditions = []
    if target_type is not None:
        conditions.append(col(AuditEvent.target_type) == target_type)
    if target_id is not None:
        conditions.append(col(AuditEvent.target_id) == target_id)
    total = session.exec(select(func.count()).select_from(AuditEvent).where(*conditions)).one()
    rows = session.exec(
        select(AuditEvent)
        .where(*conditions)
        .order_by(col(AuditEvent.created_at).desc(), col(AuditEvent.id).desc())
        .offset(pagination.skip)
        .limit(pagination.limit)
    ).all()
    return list(rows), int(total)


def resolve_time_zone(name: str) -> ZoneInfo:
    """The IANA time zone *name* names, or a validation failure that says which name it was.

    The zone database is the ``tzdata`` package where the system has none (Windows), so
    every IANA name resolves on every host. How strictly a name is matched is still the
    host's: a case-insensitive filesystem also accepts ``utc``, and a system database may
    know a few names ``tzdata`` does not (``posixrules``). The canonical spelling resolves
    everywhere, and that is the one the hub sends.
    """
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValidationFailedError(f"{name!r} is not a time zone this server knows.") from exc


def local_midnights(
    zone: ZoneInfo, *, days: int, now: datetime.datetime
) -> list[datetime.datetime]:
    """The ``days + 1`` boundaries of the last *days* calendar days in *zone*, in UTC.

    Day ``i`` runs from ``boundaries[i]`` up to ``boundaries[i + 1]``, and the last day is
    today in *zone*, so the final boundary is tomorrow's midnight there. Each midnight is
    made in the zone and only then converted, so a day that daylight saving makes 23 or 25
    hours long keeps its real length.
    """
    today = now.astimezone(zone).date()
    first = today - datetime.timedelta(days=days - 1)
    return [
        datetime.datetime.combine(
            first + datetime.timedelta(days=offset), datetime.time(), tzinfo=zone
        ).astimezone(datetime.UTC)
        for offset in range(days + 1)
    ]


def audit_activity(
    session: Session,
    *,
    days: int,
    zone: ZoneInfo,
    now: datetime.datetime | None = None,
) -> AuditActivityRead:
    """Count the trail per calendar day of *zone*: the last *days* days and the *days* before.

    One query counts every day at once, as one conditional aggregate per day over the
    window's index range. It compares the timestamp column with bound instants only, which
    reads the same on SQLite, where the column holds UTC wall time, and on PostgreSQL. The
    days are not grouped: grouping by an expression that carries bound parameters is refused
    by PostgreSQL once the parameters are bound on the server, because the select list and
    the grouping no longer read as one expression. The kinds of change and the types of
    record are grouped by their own columns, over the last *days* days only.
    """
    moment = now if now is not None else datetime.datetime.now(datetime.UTC)
    bounds = local_midnights(zone, days=2 * days, now=moment)
    created = col(AuditEvent.created_at)
    counts = session.exec(
        select(
            *(
                func.count(case(((created >= bounds[i]) & (created < bounds[i + 1]), 1)))
                for i in range(2 * days)
            )
        ).where(created >= bounds[0], created < bounds[-1])
    ).one()
    per_day = [
        AuditDayCount(date=bounds[i].astimezone(zone).date(), count=int(counts[i]))
        for i in range(2 * days)
    ]
    window = (created >= bounds[days], created < bounds[-1])
    by_action = session.exec(
        select(col(AuditEvent.action), func.count())
        .where(*window)
        .group_by(col(AuditEvent.action))
        .order_by(func.count().desc(), col(AuditEvent.action))
    ).all()
    by_target_type = session.exec(
        select(col(AuditEvent.target_type), func.count())
        .where(*window)
        .group_by(col(AuditEvent.target_type))
        .order_by(func.count().desc(), col(AuditEvent.target_type))
        .limit(ACTIVITY_TOP_TARGETS)
    ).all()
    current = per_day[days:]
    return AuditActivityRead(
        time_zone=zone.key,
        days=current,
        previous_days=per_day[:days],
        by_action=[AuditActionCount(action=action, count=int(n)) for action, n in by_action],
        by_target_type=[
            AuditTargetCount(target_type=target_type, count=int(n))
            for target_type, n in by_target_type
        ],
        total=sum(day.count for day in current),
    )


__all__ = [
    "ACTIVITY_MAX_DAYS",
    "ACTIVITY_TOP_TARGETS",
    "audit_activity",
    "list_audit_events",
    "local_midnights",
    "resolve_time_zone",
]
