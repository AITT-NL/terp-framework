"""Read access to the audit log — one paginated, newest-first query, and its activity per day.

The log is append-only (written by the sink), so this capability exposes only a
read path: a single, bounded list used by the admin router, optionally narrowed to
the one record a screen is about, and the counts a dashboard draws from. The list
mirrors the kernel's pagination contract so the trail is browsed like any other
``Page[T]``; the counts are the trail's declared statistics (ADR 0204), so the calendar
days of a zone, the bound on a breakdown and the PostgreSQL grouping rule are the
framework's, not this module's.
"""

from __future__ import annotations

import datetime
from zoneinfo import ZoneInfo

from sqlmodel import Session, col, func, select

from terp.core import (
    Dimension,
    Measure,
    PaginationParams,
    Statistics,
    TimeBucket,
    Window,
    aggregate,
    resolve_time_zone,
)

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

#: What the activity read may count, and by what. The kinds of change are a closed set, so
#: one page holds every one of them; the record types are ranked, so only the top ones show.
ACTIVITY = Statistics(
    measures=(Measure("events"),),
    dimensions=(
        Dimension("action", AuditEvent.action),  # type: ignore[arg-type]
        Dimension("target_type", AuditEvent.target_type),  # type: ignore[arg-type]
    ),
    time_buckets=(
        TimeBucket(
            "created",
            AuditEvent.created_at,  # type: ignore[arg-type]
            steps=("day",),
            max_buckets=2 * ACTIVITY_MAX_DAYS,
        ),
    ),
    max_groups=32,
)


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


def audit_activity(
    session: Session,
    *,
    days: int,
    zone: ZoneInfo,
    now: datetime.datetime | None = None,
) -> AuditActivityRead:
    """Count the trail per calendar day of *zone*: the last *days* days and the *days* before.

    Three declared aggregates over the trail (:data:`ACTIVITY`): one series of ``2 * days``
    calendar days ending today in *zone*, split into the current window and the one before
    it, and the kinds of change and the types of record over the current window alone. Each
    day is the zone's own, made from its local midnights, so a day that daylight saving
    shortens keeps its real length, on SQLite and on PostgreSQL alike.
    """
    moment = now if now is not None else datetime.datetime.now(datetime.UTC)
    today = moment.astimezone(zone).date()
    query = select(AuditEvent)
    series = Window(
        "created", start=today - datetime.timedelta(days=2 * days - 1), end=today, zone=zone, step="day"
    )
    (trail,), _ = aggregate(session, query, ACTIVITY, measures=["events"], window=series)
    per_day = [
        AuditDayCount(date=point.start.date(), count=int(point.measures["events"] or 0))
        for point in trail.series or []
    ]
    window = Window("created", start=today - datetime.timedelta(days=days - 1), end=today, zone=zone)
    by_action, _ = aggregate(
        session,
        query,
        ACTIVITY,
        measures=["events"],
        by=["action"],
        window=window,
        sort=["-events", "action"],
    )
    by_target_type, _ = aggregate(
        session,
        query,
        ACTIVITY,
        measures=["events"],
        by=["target_type"],
        window=window,
        sort=["-events", "target_type"],
        limit=ACTIVITY_TOP_TARGETS,
    )
    current = per_day[days:]
    return AuditActivityRead(
        time_zone=zone.key,
        days=current,
        previous_days=per_day[:days],
        by_action=[
            AuditActionCount(action=str(group.dimensions["action"]), count=int(group.measures["events"] or 0))
            for group in by_action
        ],
        by_target_type=[
            AuditTargetCount(
                target_type=str(group.dimensions["target_type"]),
                count=int(group.measures["events"] or 0),
            )
            for group in by_target_type
        ],
        total=sum(day.count for day in current),
    )


__all__ = [
    "ACTIVITY",
    "ACTIVITY_MAX_DAYS",
    "ACTIVITY_TOP_TARGETS",
    "audit_activity",
    "list_audit_events",
    "resolve_time_zone",
]
