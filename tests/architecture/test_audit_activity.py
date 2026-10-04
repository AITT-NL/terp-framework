"""The audit trail's activity per calendar day, counted the same on SQLite and on PostgreSQL.

Each test takes ``terp_db_url``, so it runs on SQLite and again on PostgreSQL wherever
``TERP_TEST_POSTGRES_URL`` names a server: the per-day counts are conditional aggregates over
bound instants, which is exactly the kind of query whose answer can differ between the two.
"""

from __future__ import annotations

import datetime
import uuid
from collections.abc import Iterator
from zoneinfo import ZoneInfo

import pytest
from sqlmodel import Session, create_engine

from terp.core import ValidationFailedError

from terp.capabilities.audit import AuditEvent, audit_activity
from terp.capabilities.audit.service import (
    ACTIVITY_TOP_TARGETS,
    local_midnights,
    resolve_time_zone,
)

AMSTERDAM = ZoneInfo("Europe/Amsterdam")
UTC = datetime.UTC


def at(*parts: int) -> datetime.datetime:
    """An instant in UTC."""
    return datetime.datetime(*parts, tzinfo=UTC)


@pytest.fixture
def session(terp_db_url: str) -> Iterator[Session]:
    engine = create_engine(terp_db_url)
    AuditEvent.__table__.create(engine)  # type: ignore[attr-defined]
    try:
        with Session(engine) as session:
            yield session
    finally:
        engine.dispose()


def record(session: Session, when: datetime.datetime, action: str = "updated", target: str = "Order") -> None:
    session.add(
        AuditEvent(action=action, target_type=target, target_id=str(uuid.uuid4()), created_at=when)
    )


def test_a_day_keeps_its_length_across_a_daylight_saving_change() -> None:
    # Amsterdam leaves summer time at 01:00 UTC on 25 October 2026, so that day is 25 hours
    # long: its midnight is 22:00 UTC the evening before, and the next one 23:00 UTC.
    bounds = local_midnights(AMSTERDAM, days=3, now=at(2026, 10, 27, 12))
    assert bounds == [
        at(2026, 10, 24, 22),
        at(2026, 10, 25, 23),
        at(2026, 10, 26, 23),
        at(2026, 10, 27, 23),
    ]


def test_counts_each_calendar_day_of_the_zone(session: Session) -> None:
    record(session, at(2026, 10, 21, 12))  # before the window
    record(session, at(2026, 10, 24, 21, 30))  # 23:30 summer time, 24 October
    record(session, at(2026, 10, 24, 22, 30))  # 00:30 summer time, 25 October
    record(session, at(2026, 10, 25, 22, 30))  # 23:30 winter time, still 25 October
    record(session, at(2026, 10, 25, 23, 30))  # 00:30, 26 October
    record(session, at(2026, 10, 27, 11))  # today
    record(session, at(2026, 10, 27, 23, 30))  # 00:30 on 28 October: tomorrow, not counted
    session.commit()

    activity = audit_activity(session, days=3, zone=AMSTERDAM, now=at(2026, 10, 27, 12))

    assert activity.time_zone == "Europe/Amsterdam"
    assert [(day.date.isoformat(), day.count) for day in activity.days] == [
        ("2026-10-25", 2),
        ("2026-10-26", 1),
        ("2026-10-27", 1),
    ]
    assert [(day.date.isoformat(), day.count) for day in activity.previous_days] == [
        ("2026-10-22", 0),
        ("2026-10-23", 0),
        ("2026-10-24", 1),
    ]
    assert activity.total == 4


def test_the_same_instants_fall_on_other_days_in_another_zone(session: Session) -> None:
    # 22:30 UTC on 24 October is already the 25th in Amsterdam and still the 24th in UTC.
    record(session, at(2026, 10, 24, 22, 30))
    session.commit()
    now = at(2026, 10, 27, 12)
    in_amsterdam = audit_activity(session, days=3, zone=AMSTERDAM, now=now)
    in_utc = audit_activity(session, days=3, zone=ZoneInfo("UTC"), now=now)
    assert [day.count for day in in_amsterdam.days] == [1, 0, 0]
    assert [day.count for day in in_utc.previous_days] == [0, 0, 1]
    assert in_utc.total == 0


def test_breaks_the_last_days_down_by_kind_and_by_record_type(session: Session) -> None:
    now = at(2026, 9, 30, 12)
    for _ in range(3):
        record(session, at(2026, 9, 30, 8), action="created", target="Customer")
    record(session, at(2026, 9, 29, 8), action="deleted", target="Order")
    record(session, at(2026, 9, 29, 9), action="updated", target="Order")
    record(session, at(2026, 9, 29, 10), action="updated", target="Order")
    # The days before the window are counted per day, and left out of both breakdowns.
    record(session, at(2026, 9, 25, 8), action="disclosed", target="User")
    # So is anything stamped after today: tomorrow is not in the window either.
    record(session, at(2026, 10, 1, 1), action="disclosed", target="User")
    session.commit()

    activity = audit_activity(session, days=3, zone=ZoneInfo("UTC"), now=now)

    assert [(row.action, row.count) for row in activity.by_action] == [
        ("created", 3),
        ("updated", 2),
        ("deleted", 1),
    ]
    assert [(row.target_type, row.count) for row in activity.by_target_type] == [
        ("Customer", 3),
        ("Order", 3),
    ]
    assert activity.total == 6
    assert sum(day.count for day in activity.previous_days) == 1


def test_ranks_only_the_most_changed_record_types(session: Session) -> None:
    now = at(2026, 9, 30, 12)
    for rank in range(ACTIVITY_TOP_TARGETS + 2):
        for _ in range(ACTIVITY_TOP_TARGETS + 2 - rank):
            record(session, at(2026, 9, 30, 8), target=f"Type{rank:02d}")
    session.commit()
    activity = audit_activity(session, days=1, zone=ZoneInfo("UTC"), now=now)
    assert [row.target_type for row in activity.by_target_type] == [
        f"Type{rank:02d}" for rank in range(ACTIVITY_TOP_TARGETS)
    ]
    # The types past the ranking are still counted.
    assert activity.total == sum(range(1, ACTIVITY_TOP_TARGETS + 3))


def test_an_empty_trail_counts_zero_every_day(session: Session) -> None:
    activity = audit_activity(session, days=2, zone=AMSTERDAM, now=at(2026, 9, 30, 12))
    assert [day.count for day in activity.days] == [0, 0]
    assert [day.count for day in activity.previous_days] == [0, 0]
    assert activity.by_action == []
    assert activity.by_target_type == []
    assert activity.total == 0


def test_a_time_zone_is_resolved_by_its_iana_name() -> None:
    assert resolve_time_zone("Europe/Amsterdam").key == "Europe/Amsterdam"
    with pytest.raises(ValidationFailedError, match="Mars/Olympus"):
        resolve_time_zone("Mars/Olympus")
    # A name that is not a relative key at all is refused by the zone database itself.
    with pytest.raises(ValidationFailedError):
        resolve_time_zone("Europe/../Amsterdam")
