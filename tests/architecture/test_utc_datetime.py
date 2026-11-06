"""A timestamp column stores an instant, as UTC, on every dialect (ADR 0205).

SQLite keeps a timestamp's wall time and drops its offset. Before ``UtcDateTime``, an
instant written in another zone was stored as that zone's local time, compared wrong
against every other value by the offset, and read back with no zone at all. The tests
that take ``terp_db_url`` run on SQLite and again on PostgreSQL wherever
``TERP_TEST_POSTGRES_URL`` names a server: the answer has to be the same on both.
"""

import datetime as dt
import importlib
import pkgutil
from collections.abc import Iterator
from zoneinfo import ZoneInfo

import pytest
import sqlalchemy as sa
from sqlmodel import Field, Session, SQLModel, create_engine, select
from sqlmodel.main import default_registry

import base64
import uuid

import terp.capabilities
from terp.core import (
    BaseTable,
    FilterField,
    Measure,
    Statistics,
    TimeBucket,
    UtcDateTime,
    ValidationFailedError,
    Window,
    aggregate,
    group_model,
)
from terp.core.pagination import decode_cursor
from terp.migrations._runtime import _render_item
from terp.migrations.window import record_table

UTC = dt.UTC
AMSTERDAM = ZoneInfo("Europe/Amsterdam")
#: 10:00 in Amsterdam on 6 November 2026 (CET, UTC+1) is 09:00 UTC.
LOCAL = dt.datetime(2026, 11, 6, 10, 0, tzinfo=AMSTERDAM)
INSTANT = dt.datetime(2026, 11, 6, 9, 0, tzinfo=UTC)


class Stamped(BaseTable, table=True):
    __tablename__ = "utc_datetime_stamped"
    note: str = Field(default="", max_length=20)
    happened_at: dt.datetime = Field(sa_type=UtcDateTime())  # type: ignore[call-overload]


@pytest.fixture
def engine(terp_db_url: str) -> Iterator[sa.Engine]:
    value = create_engine(terp_db_url)
    try:
        yield value
    finally:
        value.dispose()


def _written(engine: sa.Engine, kind: sa.types.TypeEngine, *values: object) -> sa.Table:
    metadata = sa.MetaData()
    table = sa.Table(
        "utc_datetime_probe",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("at", kind, nullable=True),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(table.insert(), [{"id": i, "at": v} for i, v in enumerate(values)])
    return table


def _count(engine: sa.Engine, table: sa.Table, clause: sa.ColumnElement[bool]) -> int:
    with engine.connect() as connection:
        statement = sa.select(sa.func.count()).select_from(table).where(clause)
        return connection.execute(statement).scalar_one()


def test_an_instant_written_in_another_zone_compares_as_that_instant(engine: sa.Engine) -> None:
    table = _written(engine, UtcDateTime(), LOCAL)
    assert _count(engine, table, table.c.at == INSTANT) == 1
    assert _count(engine, table, table.c.at < INSTANT + dt.timedelta(minutes=30)) == 1
    assert _count(engine, table, table.c.at > INSTANT - dt.timedelta(minutes=30)) == 1
    # The bound is an instant too: spelled in Amsterdam, it is still 09:00 UTC.
    assert _count(engine, table, table.c.at == INSTANT.astimezone(AMSTERDAM)) == 1


def test_every_value_reads_back_aware_in_utc(engine: sa.Engine) -> None:
    table = _written(engine, UtcDateTime(), LOCAL)
    with engine.connect() as connection:
        value = connection.execute(sa.select(table.c.at)).scalar_one()
    assert value == INSTANT
    assert value.tzinfo is UTC


def test_a_naive_value_is_taken_as_utc(engine: sa.Engine) -> None:
    table = _written(engine, UtcDateTime(), INSTANT.replace(tzinfo=None))
    with engine.connect() as connection:
        assert connection.execute(sa.select(table.c.at)).scalar_one() == INSTANT
    assert _count(engine, table, table.c.at == INSTANT) == 1


def test_a_null_stays_null(engine: sa.Engine) -> None:
    table = _written(engine, UtcDateTime(), None)
    with engine.connect() as connection:
        assert connection.execute(sa.select(table.c.at)).scalar_one() is None
    assert _count(engine, table, table.c.at.is_(None)) == 1


def test_an_interval_still_adds_to_a_timestamp(engine: sa.Engine) -> None:
    """``created_at + timedelta(...)`` binds the timedelta as the impl types it, an interval.

    Coerced through the type, the timedelta reached the UTC conversion and raised. On
    PostgreSQL the sum is right; SQLite's date arithmetic was never this type's to fix.
    """
    table = _written(engine, UtcDateTime(), LOCAL)
    later = table.c.at + dt.timedelta(hours=1)
    count = _count(engine, table, later > INSTANT + dt.timedelta(minutes=30))
    if engine.dialect.name == "postgresql":
        assert count == 1


def test_a_plain_date_is_its_midnight_in_utc(engine: sa.Engine) -> None:
    day = dt.date(2026, 11, 6)
    table = _written(engine, UtcDateTime(), day)
    with engine.connect() as connection:
        assert connection.execute(sa.select(table.c.at)).scalar_one() == dt.datetime(
            2026, 11, 6, tzinfo=UTC
        )
    assert _count(engine, table, table.c.at >= day) == 1
    assert _count(engine, table, table.c.at < day) == 0


def test_a_bound_outside_the_years_a_timestamp_holds_is_a_400_not_a_500() -> None:
    """An offset can carry a valid ISO string past year 1 or year 9999. Moved to UTC at the
    edge, it is a ``ValidationFailedError`` there, never an overflow inside the driver call."""
    far = dt.datetime(1, 1, 1, tzinfo=dt.timezone(dt.timedelta(hours=14)))
    raw = f"{far.isoformat()}|{uuid.uuid4()}"
    with pytest.raises(ValidationFailedError):
        decode_cursor(base64.urlsafe_b64encode(raw.encode()).decode())
    since = FilterField("since", Stamped.happened_at, op="gte")
    with pytest.raises(ValidationFailedError, match="'since'"):
        since.condition(far)
    with pytest.raises(ValidationFailedError, match="'any'"):
        FilterField("any", Stamped.happened_at, op="in").condition([INSTANT, far])


def test_a_cursor_and_a_filter_move_an_aware_bound_to_utc() -> None:
    position = f"{LOCAL.isoformat()}|{uuid.uuid4()}"
    at, _ = decode_cursor(base64.urlsafe_b64encode(position.encode()).decode())
    assert (at, at.tzinfo) == (INSTANT, UTC)
    naive = f"{INSTANT.replace(tzinfo=None).isoformat()}|{uuid.uuid4()}"
    at, _ = decode_cursor(base64.urlsafe_b64encode(naive.encode()).decode())
    assert at.tzinfo is None  # left to the column's type, which takes it as UTC
    condition = FilterField("since", Stamped.happened_at, op="gte").condition(LOCAL)
    bound = condition.right.value  # type: ignore[attr-defined]
    assert (bound, bound.tzinfo) == (INSTANT, UTC)


def test_a_statistic_over_it_is_typed_as_a_timestamp() -> None:
    """A decorator answers ``object`` for its Python type unless it says otherwise, which
    typed a figure over this column as anything in the API contract."""
    assert UtcDateTime().python_type is dt.datetime
    statistics = Statistics(
        measures=(Measure("first", Stamped.happened_at, op="min"), Measure("stamps")),
    )
    schema = group_model(statistics, "Stamps").model_json_schema()
    first = schema["$defs"]["StampsMeasures"]["properties"]["first"]
    assert {"format": "date-time", "type": "string"} in first["anyOf"]


def test_a_naive_value_is_utc_whatever_zone_the_server_session_is_in(terp_pg_url: str) -> None:
    """On PostgreSQL the session's zone used to decide what a naive value meant. On a server
    whose session runs in Amsterdam, the plain type stored a naive 10:00 as 09:00 UTC; this
    type stores it as 10:00 UTC, the meaning it has on SQLite, and reads every value back in
    UTC rather than in the session's zone."""
    amsterdam = create_engine(
        terp_pg_url, connect_args={"options": "-c timezone=Europe/Amsterdam"}
    )
    naive, day = dt.datetime(2026, 11, 6, 10, 0), dt.date(2026, 11, 6)
    try:
        plain = _written(amsterdam, sa.DateTime(timezone=True), naive, day)
        with amsterdam.connect() as connection:
            stored, midnight = connection.execute(sa.select(plain.c.at).order_by(plain.c.id)).scalars()
        assert stored == dt.datetime(2026, 11, 6, 9, 0, tzinfo=UTC)
        assert stored.utcoffset() == dt.timedelta(hours=1)  # the session's zone
        assert midnight == dt.datetime(2026, 11, 5, 23, 0, tzinfo=UTC)  # Amsterdam's midnight
        plain.drop(amsterdam)
        utc = _written(amsterdam, UtcDateTime(), naive, day)
        with amsterdam.connect() as connection:
            stored, midnight = connection.execute(sa.select(utc.c.at).order_by(utc.c.id)).scalars()
            on_the_day = connection.execute(
                sa.select(sa.func.count()).select_from(utc).where(utc.c.at < day)
            ).scalar_one()
        assert (stored, stored.tzinfo) == (dt.datetime(2026, 11, 6, 10, 0, tzinfo=UTC), UTC)
        assert (midnight, midnight.tzinfo) == (dt.datetime(2026, 11, 6, tzinfo=UTC), UTC)
        assert on_the_day == 0  # the date compares as its UTC midnight too
    finally:
        amsterdam.dispose()


def test_the_plain_type_is_right_on_postgresql_and_off_by_the_offset_on_sqlite(
    engine: sa.Engine,
) -> None:
    """What ``UtcDateTime`` exists for, pinned. If SQLite ever keeps the offset, this fails
    and the type is worth reconsidering."""
    table = _written(engine, sa.DateTime(timezone=True), LOCAL)
    expected = 0 if engine.dialect.name == "sqlite" else 1
    assert _count(engine, table, table.c.at == INSTANT) == expected


def test_a_table_model_keeps_the_instant_through_the_orm(engine: sa.Engine) -> None:
    SQLModel.metadata.create_all(engine, tables=[Stamped.__table__])  # type: ignore[attr-defined]
    with Session(engine) as session:
        session.add(Stamped(note="local", happened_at=LOCAL, created_at=LOCAL))
        session.commit()
    with Session(engine) as session:
        row = session.exec(select(Stamped).where(Stamped.happened_at == INSTANT)).one()
        assert (row.happened_at, row.created_at) == (INSTANT, INSTANT)
        assert row.happened_at.tzinfo is UTC
        assert row.created_at is not None and row.created_at.tzinfo is UTC
        # BaseTable's own timestamps take the instant the same way (they are UtcDateTime).
        assert session.exec(select(Stamped).where(Stamped.created_at == INSTANT)).one() is not None


def test_a_statistic_puts_a_late_local_instant_in_its_own_day(engine: sa.Engine) -> None:
    """ADR 0204's caveat, closed: 23:30 in Amsterdam on 1 November is 22:30 UTC, the 1st.

    Stored as its wall time it read as later than the 2nd's first instant (23:00 UTC on
    the 1st), so on SQLite it was counted on the 2nd.
    """
    SQLModel.metadata.create_all(engine, tables=[Stamped.__table__])  # type: ignore[attr-defined]
    late = dt.datetime(2026, 11, 1, 23, 30, tzinfo=AMSTERDAM)
    with Session(engine) as session:
        session.add(Stamped(note="late", happened_at=late))
        session.commit()
        statistics = Statistics(
            measures=(Measure("stamps"),),
            time_buckets=(TimeBucket("happened", Stamped.happened_at, steps=("day",)),),
        )
        window = Window(
            "happened",
            start=dt.date(2026, 11, 1),
            end=dt.date(2026, 11, 2),
            zone=AMSTERDAM,
            step="day",
        )
        (group,), _ = aggregate(
            session, select(Stamped), statistics, measures=["stamps"], window=window
        )
    assert [(point.date, point.measures["stamps"]) for point in group.series or []] == [
        (dt.date(2026, 11, 1), 1),
        (dt.date(2026, 11, 2), 0),
    ]


def _import_every_capability_model() -> None:
    for module in pkgutil.iter_modules(terp.capabilities.__path__):
        name = f"terp.capabilities.{module.name}.models"
        try:
            importlib.import_module(name)
        except ModuleNotFoundError as exc:
            if exc.name != name:
                raise  # a models module that exists and fails to import is a failure


def _stores_a_timestamp(column: sa.Column[object]) -> bool:
    return isinstance(column.type, sa.DateTime) or isinstance(
        getattr(column.type, "impl", None), sa.DateTime
    )


def test_every_timestamp_the_framework_declares_is_a_utc_datetime() -> None:
    """A framework table never stores an instant the SQLite way. A new framework column
    that reaches for ``DateTime(timezone=True)`` fails here, not on a reader's clock."""
    _import_every_capability_model()
    offenders = [
        f"{mapper.class_.__module__}.{mapper.class_.__name__}.{column.name}"
        for mapper in default_registry.mappers
        if mapper.class_.__module__.startswith("terp.")
        for column in mapper.local_table.columns
        if _stores_a_timestamp(column) and not isinstance(column.type, UtcDateTime)
    ]
    assert offenders == []
    stamped = {
        mapper.class_.__module__.split(".")[2]
        for mapper in default_registry.mappers
        if mapper.class_.__module__.startswith("terp.capabilities.")
        and any(_stores_a_timestamp(column) for column in mapper.local_table.columns)
    }
    # The sweep saw the capabilities it is about: it cannot pass by finding nothing.
    assert {"audit", "identity", "leases", "outbox"} <= stamped
    # The migration record is a Core table of the framework's own, outside any mapper.
    assert isinstance(record_table("sqlite").c.applied_at.type, UtcDateTime)


def test_a_revision_writes_it_as_the_type_it_stores_as() -> None:
    assert _render_item("type", UtcDateTime(), None) == "sa.DateTime(timezone=True)"
    assert _render_item("type", sa.DateTime(timezone=True), None) is False
    assert _render_item("column", UtcDateTime(), None) is False
    assert repr(UtcDateTime()) == "UtcDateTime()"
