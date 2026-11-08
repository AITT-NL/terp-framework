"""Declared statistics on a service: what may be counted, by what, and what is refused (ADR 0204).

The tests that take ``terp_db_url`` run on SQLite and again on PostgreSQL wherever
``TERP_TEST_POSTGRES_URL`` names a server: grouping, conditional bucketing and decimal sums are
exactly where the two dialects could disagree.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Iterator
from decimal import Decimal

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient
from sqlalchemy import JSON, Boolean, DateTime, MetaData, Numeric, String, cast, column, func, literal_column, text, type_coerce
from sqlalchemy.types import NullType
from sqlalchemy.orm import aliased
from sqlmodel import Field, Session, SQLModel, create_engine, select

from terp.core import (
    EDITOR,
    AggregateGroup,
    BaseSchema,
    BaseService,
    BaseTable,
    BaseUpdateSchema,
    Dimension,
    FilterField,
    Measure,
    ModuleSpec,
    Page,
    PaginationParams,
    Personal,
    Policy,
    Principal,
    SessionDep,
    SoftDeleteMixin,
    Statistics,
    StatisticsQueryDep,
    TimeBucket,
    ValidationFailedError,
    Window,
    aggregate,
    create_app,
    resolve_time_zone,
)
from terp.core import aggregation
from terp.core.aggregation import declaration_refusal, window_bounds, window_steps
from terp.core.db import get_session
from terp.core._internal.session_guard import WriteGuardedSession

AMSTERDAM = "Europe/Amsterdam"


def at(*parts: int) -> dt.datetime:
    return dt.datetime(*parts, tzinfo=dt.UTC)


class Sale(SoftDeleteMixin, BaseTable, table=True):
    __tablename__ = "aggregation_sale"
    region: str | None = Field(default=None, max_length=20)
    channel: str = Field(default="web", max_length=20)
    amount: Decimal = Field(default=Decimal("0"), sa_type=Numeric(12, 2))  # type: ignore[call-overload]
    units: int = 0
    sold_at: dt.datetime = Field(sa_type=DateTime(timezone=True))  # type: ignore[call-overload]
    buyer_email: str = Personal(default="buyer@example.com", max_length=320)
    birth_date: dt.datetime | None = Personal(default=None, sa_type=DateTime(timezone=True))


class SaleCreate(BaseSchema):
    region: str | None = Field(default=None, max_length=20)


class SaleUpdate(BaseUpdateSchema):
    region: str | None = Field(default=None, max_length=20)


class Sales(BaseService[Sale, SaleCreate, SaleUpdate]):
    model = Sale
    filterable = (FilterField("channel", Sale.channel),)
    measures = (
        Measure("sales"),
        Measure("revenue", Sale.amount, op="sum"),
        Measure("mean_units", Sale.units, op="avg"),
        Measure("most_units", Sale.units, op="max"),
        Measure("first_sale", Sale.sold_at, op="min"),
        Measure("buyers", Sale.buyer_email, op="count_distinct"),
    )
    dimensions = (Dimension("region", Sale.region), Dimension("channel", Sale.channel))
    time_buckets = (TimeBucket("sold", Sale.sold_at, steps=("day", "week", "month"), max_buckets=62),)
    max_groups = 5


class ShopSales(Sales):
    """A service narrowing every read with a business filter; statistics must honour it."""

    def business_filters(self):
        return (Sale.channel == "shop",)


ROWS = [
    # region, channel, amount, units, sold_at, buyer
    ("north", "web", "10.50", 1, at(2026, 10, 1, 9), "a@example.com"),
    ("north", "web", "20.25", 3, at(2026, 10, 15, 9), "b@example.com"),
    ("south", "shop", "5.00", 2, at(2026, 10, 15, 9), "a@example.com"),
    ("south", "web", "7.00", 1, at(2026, 11, 2, 9), "c@example.com"),
    (None, "shop", "1.00", 4, at(2026, 11, 3, 9), "a@example.com"),
    # 23:30 UTC on 25 October is already the 26th in Amsterdam, after the clocks went back.
    ("north", "shop", "100.00", 5, at(2026, 10, 25, 23, 30), "d@example.com"),
]


@pytest.fixture
def engine(terp_db_url: str) -> Iterator[object]:
    value = create_engine(terp_db_url)
    SQLModel.metadata.create_all(value, tables=[Sale.__table__])  # type: ignore[attr-defined]
    with Session(value) as session:
        for region, channel, amount, units, sold_at, buyer in ROWS:
            session.add(
                Sale(
                    region=region,
                    channel=channel,
                    amount=Decimal(amount),
                    units=units,
                    sold_at=sold_at,
                    buyer_email=buyer,
                )
            )
        # Soft-deleted: every figure must leave it out.
        session.add(Sale(region="north", amount=Decimal("5000"), units=99, sold_at=at(2026, 10, 2, 9), deleted_at=at(2026, 10, 3)))
        session.commit()
    try:
        yield value
    finally:
        value.dispose()


def figures(groups: list[AggregateGroup]) -> list[tuple[dict, dict]]:
    return [(group.dimensions, group.measures) for group in groups]


# ---- the figures ----------------------------------------------------------------------------


def test_the_whole_scope_is_one_group_with_every_figure(engine) -> None:
    with WriteGuardedSession(engine) as session:
        groups, total = Sales().aggregate(
            session, measures=["sales", "revenue", "mean_units", "most_units", "first_sale", "buyers"]
        )
    assert total == 1
    (group,) = groups
    assert group.dimensions == {}
    assert group.series is None
    measures = group.measures
    assert measures["sales"] == 6
    assert measures["revenue"] == Decimal("143.75")
    assert measures["mean_units"] == pytest.approx(16 / 6)
    assert isinstance(measures["mean_units"], float)
    assert measures["most_units"] == 5
    assert measures["first_sale"].astimezone(dt.UTC) == at(2026, 10, 1, 9)
    assert measures["buyers"] == 4


def test_a_count_alone_counts_the_rows_of_a_model_with_no_row_scope() -> None:
    # A count over no dimension projects no column of the model; the FROM must survive.
    class Tally(BaseTable, table=True):
        __tablename__ = "aggregation_tally"

    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine, tables=[Tally.__table__])  # type: ignore[attr-defined]
    with Session(engine) as session:
        session.add_all([Tally(), Tally(), Tally()])
        session.commit()
        statistics = Statistics(measures=(Measure("rows"),))
        groups, total = aggregate(session, select(Tally), statistics, measures=["rows"])
    assert (total, groups[0].measures) == (1, {"rows": 3})


def test_groups_by_a_dimension_largest_first_with_a_none_group(engine) -> None:
    with WriteGuardedSession(engine) as session:
        groups, total = Sales().aggregate(session, measures=["sales", "revenue"], by=["region"])
    assert total == 3
    assert figures(groups) == [
        ({"region": "north"}, {"sales": 3, "revenue": Decimal("130.75")}),
        ({"region": "south"}, {"sales": 2, "revenue": Decimal("12.00")}),
        ({"region": None}, {"sales": 1, "revenue": Decimal("1.00")}),
    ]


def test_two_dimensions_sorted_as_asked_and_paged(engine) -> None:
    with WriteGuardedSession(engine) as session:
        first, total = Sales().aggregate(
            session, measures=["sales"], by=["region", "channel"], sort=["region", "-sales"], limit=2
        )
        rest, again = Sales().aggregate(
            session, measures=["sales"], by=["region", "channel"], sort=["region", "-sales"], skip=2, limit=2
        )
    assert total == again == 5
    seen = [group.dimensions for group in first + rest]
    assert seen[:2] == [{"region": "north", "channel": "web"}, {"region": "north", "channel": "shop"}]
    assert seen[2:] == [{"region": "south", "channel": "shop"}, {"region": "south", "channel": "web"}]


def test_a_page_of_groups_is_a_page(engine) -> None:
    pagination = PaginationParams(skip=0, limit=2)
    with WriteGuardedSession(engine) as session:
        groups, total = Sales().aggregate(session, measures=["sales"], by=["region"], limit=pagination.limit)
    page = Page[AggregateGroup].of(groups, total, pagination)
    assert page.total == 3 and len(page.items) == 2
    assert page.model_dump(mode="json")["items"][0] == {
        "dimensions": {"region": "north"},
        "measures": {"sales": 3},
        "series": None,
    }


def test_declared_filters_narrow_the_figures(engine) -> None:
    with WriteGuardedSession(engine) as session:
        groups, _ = Sales().aggregate(session, measures=["sales"], filters={"channel": "shop"})
        with pytest.raises(ValidationFailedError, match="Unknown filter 'region'"):
            Sales().aggregate(session, measures=["sales"], filters={"region": "north"})
    assert groups[0].measures == {"sales": 3}


def test_business_filters_and_soft_delete_cannot_be_dropped(engine) -> None:
    with WriteGuardedSession(engine) as session:
        groups, _ = ShopSales().aggregate(session, measures=["sales", "revenue"])
    assert groups[0].measures == {"sales": 3, "revenue": Decimal("106.00")}


# ---- windows and series -----------------------------------------------------------------


def test_a_window_without_a_step_narrows_the_rows_and_draws_no_series(engine) -> None:
    window = Window("sold", start=dt.date(2026, 11, 1), end=dt.date(2026, 11, 30), zone=AMSTERDAM)
    with WriteGuardedSession(engine) as session:
        groups, _ = Sales().aggregate(session, measures=["sales"], window=window)
    assert groups[0].measures == {"sales": 2}
    assert groups[0].series is None


def test_an_empty_window_answers_zero_not_nothing(engine) -> None:
    # SQL answers NULL for a sum over no rows; a statistic answers what a chart can draw.
    window = Window("sold", start=dt.date(2025, 1, 1), end=dt.date(2025, 1, 31), zone=AMSTERDAM)
    with WriteGuardedSession(engine) as session:
        (group,), total = Sales().aggregate(session, measures=["sales", "revenue", "mean_units"], window=window)
        by_region, none = Sales().aggregate(session, measures=["sales"], by=["region"], window=window)
    assert (total, group.measures) == (1, {"sales": 0, "revenue": 0, "mean_units": None})
    assert (by_region, none) == ([], 0)


def test_a_monthly_series_per_group_starts_at_local_midnights(engine) -> None:
    window = Window("sold", start=dt.date(2026, 10, 1), end=dt.date(2026, 11, 30), zone=AMSTERDAM, step="month")
    with WriteGuardedSession(engine) as session:
        groups, _ = Sales().aggregate(
            session, measures=["sales", "revenue", "mean_units"], by=["region"], window=window, sort=["region"]
        )
    north = groups[0]
    assert north.dimensions == {"region": "north"}
    assert [point.start.isoformat() for point in north.series or []] == [
        "2026-10-01T00:00:00+02:00",
        "2026-11-01T00:00:00+01:00",
    ]
    assert [point.date.isoformat() for point in north.series or []] == ["2026-10-01", "2026-11-01"]
    # An empty step counts zero, adds zero, and has no average.
    assert [point.measures for point in north.series or []] == [
        {"sales": 3, "revenue": Decimal("130.75"), "mean_units": pytest.approx(3.0)},
        {"sales": 0, "revenue": 0, "mean_units": None},
    ]
    nobody = groups[-1]
    assert nobody.dimensions == {"region": None}
    assert [point.measures["sales"] for point in nobody.series or []] == [0, 1]


def test_a_day_is_the_zones_own_across_a_daylight_saving_change(engine) -> None:
    window = Window("sold", start=dt.date(2026, 10, 24), end=dt.date(2026, 10, 27), zone=AMSTERDAM, step="day")
    with WriteGuardedSession(engine) as session:
        groups, _ = Sales().aggregate(session, measures=["sales"], window=window)
    series = groups[0].series or []
    assert [point.start.date().isoformat() for point in series] == [
        "2026-10-24",
        "2026-10-25",
        "2026-10-26",
        "2026-10-27",
    ]
    assert [point.measures["sales"] for point in series] == [0, 0, 1, 0]
    # The 25th had 25 hours there: its successor starts 25 real hours after it. (Two
    # datetimes in one ZoneInfo subtract as wall clocks, so measure the gap in UTC.)
    gap = series[2].start.astimezone(dt.UTC) - series[1].start.astimezone(dt.UTC)
    assert gap == dt.timedelta(hours=25)


def test_a_weekly_series_starts_on_monday_and_may_begin_part_way(engine) -> None:
    window = Window("sold", start=dt.date(2026, 10, 14), end=dt.date(2026, 10, 27), zone="UTC", step="week")
    with WriteGuardedSession(engine) as session:
        groups, _ = Sales().aggregate(session, measures=["sales"], window=window)
    series = groups[0].series or []
    assert [point.start.date().isoformat() for point in series] == ["2026-10-14", "2026-10-19", "2026-10-26"]
    assert [point.measures["sales"] for point in series] == [2, 1, 0]


def test_window_bounds_cut_a_window_into_its_steps() -> None:
    zone = resolve_time_zone("UTC")
    bounds = window_bounds(Window("sold", dt.date(2026, 1, 30), dt.date(2026, 3, 2), zone, "month"), zone)
    assert [bound.date().isoformat() for bound in bounds] == [
        "2026-01-30",
        "2026-02-01",
        "2026-03-01",
        "2026-03-03",
    ]
    assert len(window_bounds(Window("sold", dt.date(2026, 1, 1), dt.date(2026, 1, 1), zone), zone)) == 2
    with pytest.raises(ValidationFailedError, match="end is on or after its start"):
        window_bounds(Window("sold", dt.date(2026, 1, 2), dt.date(2026, 1, 1), zone, "day"), zone)


@pytest.mark.parametrize("step", ["day", "week", "month"])
def test_a_window_s_steps_are_counted_as_they_are_built(step: str) -> None:
    # The caps are judged on the count, before a bound exists, so it must be the bounds' own.
    zone = resolve_time_zone("UTC")
    first = dt.date(2026, 1, 1)
    for start in (first + dt.timedelta(days=offset) for offset in range(0, 40, 3)):
        for length in (0, 1, 6, 7, 8, 27, 31, 59, 60, 400):
            window = Window("sold", start, start + dt.timedelta(days=length), zone, step)
            assert window_steps(window) == len(window_bounds(window, zone)) - 1, (start, length)


def test_a_window_of_millennia_is_refused_before_a_bound_is_built(engine, monkeypatch) -> None:
    # Building every day from year 1 to 9999 took seconds and hundreds of megabytes before the
    # cap refused it; the count is arithmetic now, and no bound is built for a refused window.
    def built(*_args: object) -> None:  # pragma: no cover - the test fails if it is reached
        raise AssertionError("a bound was built for a window the caps refuse")

    monkeypatch.setattr(aggregation, "window_bounds", built)
    window = Window("sold", dt.date(1, 1, 1), dt.date(9999, 12, 30), "UTC", "day")
    with WriteGuardedSession(engine) as session, pytest.raises(ValidationFailedError, match="holds 3652058 days"):
        Sales().aggregate(session, measures=["sales"], window=window)


# ---- refusals at the request ------------------------------------------------------------


@pytest.mark.parametrize(
    ("ask", "words"),
    [
        ({"measures": []}, "at least one measure"),
        ({"measures": ["profit"]}, "Unknown measure 'profit'. Declared measures: buyers, first_sale"),
        ({"measures": ["sales"], "by": ["buyer_email"]}, "Unknown dimension 'buyer_email'"),
        ({"measures": ["sales"], "limit": 6}, "holds 1 to 5; 6 was asked"),
        ({"measures": ["sales"], "limit": 0}, "holds 1 to 5; 0 was asked"),
        ({"measures": ["sales"], "skip": -1}, "starts at 0 or later; -1 was asked"),
        ({"measures": ["sales", "sales"]}, "Ask for each measure once; 'sales' came twice"),
        ({"measures": ["sales"], "by": ["region", "region"]}, "Ask for each dimension once"),
        ({"measures": ["sales"], "by": ["region"], "sort": ["units"]}, "Unknown sort key 'units'"),
        ({"measures": ["sales"], "window": Window("paid", dt.date(2026, 1, 1), dt.date(2026, 1, 2), AMSTERDAM)}, "Unknown time bucket 'paid'"),
        ({"measures": ["sales"], "window": Window("sold", dt.date(2026, 1, 1), dt.date(2026, 1, 2), "Mars/Olympus")}, "'Mars/Olympus' is not a time zone"),
        ({"measures": ["sales"], "window": Window("sold", dt.date(2026, 1, 2), dt.date(2026, 1, 1), AMSTERDAM)}, "end is on or after its start"),
        ({"measures": ["sales"], "window": Window("sold", dt.date(2026, 1, 1), dt.date(2026, 12, 31), AMSTERDAM, "day")}, "holds 365 days; a series holds at most 62"),
    ],
)
def test_an_undeclared_or_unbounded_ask_is_refused(engine, ask: dict, words: str) -> None:
    with WriteGuardedSession(engine) as session, pytest.raises(ValidationFailedError, match=words):
        Sales().aggregate(session, **ask)


def test_a_step_the_bucket_does_not_offer_is_refused(engine) -> None:
    statistics = Statistics(
        measures=(Measure("sales"),), time_buckets=(TimeBucket("sold", Sale.sold_at, steps=("month",)),)
    )
    window = Window("sold", dt.date(2026, 10, 1), dt.date(2026, 10, 31), AMSTERDAM, "day")
    with WriteGuardedSession(engine) as session, pytest.raises(ValidationFailedError, match="steps by month, not 'day'"):
        aggregate(session, select(Sale), statistics, measures=["sales"], window=window)


# ---- refusals at the declaration ----------------------------------------------------------


@pytest.mark.parametrize(
    ("declare", "words"),
    [
        (lambda: Measure("Revenue", Sale.amount, op="sum"), "lower_snake_case"),
        (lambda: Measure("revenue", op="sum"), "needs the column it aggregates"),
        (lambda: Dimension("Region", Sale.region), "lower_snake_case"),
        (lambda: TimeBucket("Sold", Sale.sold_at), "lower_snake_case"),
        (lambda: TimeBucket("sold", Sale.sold_at, steps=()), "declares no step"),
        (lambda: Statistics(measures=(Measure("x"), Measure("x"))), "'x' more than once"),
        (lambda: Statistics(measures=(Measure("x"),), dimensions=(Dimension("by_email", Sale.buyer_email),)), "groups by 'by_email', a field declared personal"),
        (lambda: Statistics(measures=(Measure("x"),), time_buckets=(TimeBucket("born", Sale.birth_date),)), "buckets by 'born', a field declared personal"),
        (lambda: Statistics(measures=(Measure("latest_email", Sale.buyer_email, op="max"),)), "max over a field declared personal"),
        (lambda: Statistics(measures=(Measure("born", Sale.birth_date, op="min"),)), "min over a field declared personal"),
        # Each of these failed on every request on PostgreSQL, and a sum of text read 0 on SQLite.
        (lambda: Statistics(measures=(Measure("regions", Sale.region, op="sum"),)), "sum over a str column, and sum adds up numbers only"),
        (lambda: Statistics(measures=(Measure("latest", Sale.id, op="max"),)), "max over a UUID column, and max orders numbers, text and times only"),
        (lambda: Statistics(measures=(Measure("any", cast(Sale.units, Boolean), op="max"),)), "max over a bool column"),
        (lambda: Statistics(measures=(Measure("mean", cast(Sale.units, Boolean), op="avg"),)), "avg over a bool column"),
        (lambda: Statistics(measures=(Measure("x"),), dimensions=(Dimension("payload", cast(Sale.region, JSON)),)), "groups by 'payload', a dict column"),
    ],
)
def test_a_declaration_that_could_not_be_honoured_is_refused_when_made(declare, words: str) -> None:
    with pytest.raises(TypeError, match=words):
        declare()


def test_a_type_the_statistic_cannot_read_is_left_to_the_database() -> None:
    from types import SimpleNamespace

    from terp.core.aggregation_types import value_type

    class Undeclared:
        @property
        def python_type(self) -> type:
            raise NotImplementedError

    assert value_type(SimpleNamespace(type=Undeclared())) is None
    assert value_type(type_coerce(Sale.units, NullType())) is None
    assert value_type(Sale.region) is str, "a decorator is read as the type it stores"
    Statistics(measures=(Measure("odd", type_coerce(Sale.units, NullType()), op="sum"),))


def test_a_service_that_would_hand_back_a_persons_value_is_refused_when_defined() -> None:
    with pytest.raises(TypeError, match="LeakySales declares 'spend' as sum over a field declared personal"):

        class LeakySales(BaseService[Sale, SaleCreate, SaleUpdate]):
            model = Sale
            measures = (Measure("spend", Sale.birth_date, op="sum"),)


PERSONAL_EXPRESSIONS = {
    "under a function": lambda: func.lower(Sale.buyer_email),
    "under a cast": lambda: cast(Sale.buyer_email, String),
    "under a label": lambda: Sale.buyer_email.label("who"),
    "through the Core table": lambda: Sale.__table__.c.buyer_email,  # type: ignore[attr-defined]
    "through a copy of the table": lambda: Sale.__table__.to_metadata(MetaData()).c.buyer_email,  # type: ignore[attr-defined]
    "through an ORM alias": lambda: aliased(Sale).buyer_email,
    "through a Core alias": lambda: Sale.__table__.alias().c.buyer_email,  # type: ignore[attr-defined]
    "in a subquery's column": lambda: select(func.lower(Sale.buyer_email).label("who")).subquery().c.who,
}


@pytest.mark.parametrize("shape", sorted(PERSONAL_EXPRESSIONS))
def test_a_personal_field_is_refused_wherever_an_expression_reads_it(shape: str) -> None:
    # Each of these grouped by the buyer's address, a group per person, until it was refused.
    expression = PERSONAL_EXPRESSIONS[shape]()
    with pytest.raises(TypeError, match=r"groups by 'who', a field declared personal \(Sale\.buyer_email\)"):
        Statistics(measures=(Measure("x"),), dimensions=(Dimension("who", expression),))
    with pytest.raises(TypeError, match=r"buckets by 'when', a field declared personal \(Sale\.buyer_email\)"):
        Statistics(measures=(Measure("x"),), time_buckets=(TimeBucket("when", expression),))
    with pytest.raises(TypeError, match=r"as max over a field declared personal \(Sale\.buyer_email\)"):
        Statistics(measures=(Measure("latest", expression, op="max"),))


@pytest.mark.parametrize(
    "expression",
    [literal_column("buyer_email"), column("buyer_email"), text("buyer_email")],
    ids=["literal column", "bare name", "text"],
)
def test_sql_that_names_no_model_column_is_refused_as_possibly_personal(expression) -> None:
    with pytest.raises(TypeError, match="groups by 'who', SQL that names no model column"):
        Statistics(measures=(Measure("x"),), dimensions=(Dimension("who", expression),))


def test_an_expression_over_fields_that_are_not_personal_is_declared() -> None:
    lowered = Statistics(measures=(Measure("x"),), dimensions=(Dimension("region", func.lower(Sale.region)),))
    assert lowered.dimensions[0].name == "region"


def test_only_counts_may_run_over_personal_data() -> None:
    assert (
        declaration_refusal(
            (Measure("buyers", Sale.buyer_email, op="count_distinct"), Measure("rows")),
            (),
            (),
            owner="Sales",
        )
        == ""
    )


def test_a_unique_id_keeps_the_page_stable_across_requests(engine) -> None:
    # Dimensions break every tie, so equal figures never swap between two pages.
    with WriteGuardedSession(engine) as session:
        ids = [
            uuid.uuid5(uuid.NAMESPACE_URL, str(group.dimensions))
            for skip in (0, 2, 4)
            for group in Sales().aggregate(session, measures=["sales"], by=["region", "channel"], skip=skip, limit=2)[0]
        ]
    assert len(ids) == len(set(ids)) == 5


# ---- personal data, the joint cap, the typed response and the HTTP surface ------------------


class BuyerSales(Sales):
    """The list may filter by the buyer's address; a statistic may not."""

    filterable = (*Sales.filterable, FilterField("buyer", Sale.buyer_email, op="contains"))


def test_a_statistic_is_never_narrowed_by_a_personal_filter(engine) -> None:
    # Counts filtered by a personal field would answer for one person: an address can be
    # read off them one character at a time.
    with WriteGuardedSession(engine) as session:
        with pytest.raises(ValidationFailedError, match="Filter 'buyer' narrows by a field declared personal"):
            BuyerSales().aggregate(session, measures=["sales"], filters={"buyer": "a@"})
        # An absent value is no filter, so a route may forward the list's filters unbranched.
        groups, _ = BuyerSales().aggregate(session, measures=["sales"], filters={"buyer": None})
        rows, total = BuyerSales().list(session, skip=0, limit=10, filters={"buyer": "a@"})
    assert groups[0].measures == {"sales": 6}
    assert total == 3 and len(rows) == 3


class LoweredBuyerSales(Sales):
    """The list may filter by the buyer's address under a function; a statistic still may not."""

    filterable = (*Sales.filterable, FilterField("buyer", func.lower(Sale.buyer_email), op="contains"))


def test_a_statistic_is_never_narrowed_by_an_expression_of_a_personal_field(engine) -> None:
    with WriteGuardedSession(engine) as session:
        refused = r"Filter 'buyer' narrows by a field declared personal \(Sale\.buyer_email\)"
        with pytest.raises(ValidationFailedError, match=refused):
            LoweredBuyerSales().aggregate(session, measures=["sales"], filters={"buyer": "a@"})
        _, total = LoweredBuyerSales().list(session, skip=0, limit=10, filters={"buyer": "a@"})
    assert total == 3


def test_a_page_of_series_is_capped_by_its_points(engine) -> None:
    statistics = Statistics(
        measures=(Measure("sales"),),
        dimensions=(Dimension("region", Sale.region),),
        time_buckets=(TimeBucket("sold", Sale.sold_at, steps=("day",)),),
        max_points=60,
    )
    window = Window("sold", dt.date(2026, 10, 1), dt.date(2026, 10, 31), AMSTERDAM, "day")
    with WriteGuardedSession(engine) as session:
        with pytest.raises(ValidationFailedError, match="3 groups of 31 days would be 93 points"):
            aggregate(session, select(Sale), statistics, measures=["sales"], by=["region"], window=window, limit=3)
        groups, _ = aggregate(session, select(Sale), statistics, measures=["sales"], by=["region"], window=window, limit=1)
    assert len(groups[0].series or []) == 31


class IdSales(Sales):
    """Grouped by the id every Terp row has, with a maximum over text."""

    measures = (Measure("sales"), Measure("last_region", Sale.region, op="max"))
    dimensions = (Dimension("sale", Sale.id),)


def test_a_group_by_an_id_and_a_maximum_of_text_answer(engine) -> None:
    """Each was a 500 on every request: the values came back as a UUID and as text, which the
    group refused, though every Terp id is a UUID."""
    with WriteGuardedSession(engine) as session:
        groups, total = IdSales().aggregate(session, measures=["sales"], by=["sale"], limit=5)
        whole, _ = IdSales().aggregate(session, measures=["last_region"])
    assert total == 6 and all(isinstance(group.dimensions["sale"], uuid.UUID) for group in groups)
    assert whole[0].measures == {"last_region": "south"}


def test_a_series_without_a_dimension_is_one_group_to_the_points_cap(engine) -> None:
    """Without a dimension there is one group, but the cap counted the page size asked for, so
    a year of days over the whole scope was refused at the default page size."""
    statistics = Statistics(
        measures=(Measure("sales"),),
        dimensions=(Dimension("region", Sale.region),),
        time_buckets=(TimeBucket("sold", Sale.sold_at, steps=("day",)),),
        max_points=60,
    )
    window = Window("sold", dt.date(2026, 10, 1), dt.date(2026, 10, 31), AMSTERDAM, "day")
    with WriteGuardedSession(engine) as session:
        groups, _ = aggregate(session, select(Sale), statistics, measures=["sales"], window=window, limit=3)
    assert len(groups) == 1 and len(groups[0].series or []) == 31


class LongSales(Sales):
    time_buckets = (TimeBucket("sold", Sale.sold_at, steps=("day",), max_buckets=800),)


def test_a_series_longer_than_one_compound_select_of_sqlite_answers(engine) -> None:
    """SQLite reads at most 500 terms of one compound SELECT, and the steps were one."""
    window = Window("sold", dt.date(2025, 1, 1), dt.date(2026, 12, 31), "UTC", "day")
    with WriteGuardedSession(engine) as session:
        groups, _ = LongSales().aggregate(session, measures=["sales"], window=window, limit=1)
    series = groups[0].series or []
    assert len(series) == 730
    counted = {point.date.isoformat(): point.measures["sales"] for point in series if point.measures["sales"]}
    assert counted == {"2026-10-01": 1, "2026-10-15": 2, "2026-10-25": 1, "2026-11-02": 1, "2026-11-03": 1}


def test_a_day_the_zone_skipped_is_labelled_by_its_own_date(engine) -> None:
    """Samoa skipped 30 December 2011. Its step began where the 31st did and was labelled the
    31st, so the series named one day twice and the 30th not at all."""
    window = Window("sold", dt.date(2011, 12, 28), dt.date(2012, 1, 1), "Pacific/Apia", "day")
    with WriteGuardedSession(engine) as session:
        groups, _ = Sales().aggregate(session, measures=["sales"], window=window)
    series = groups[0].series or []
    assert [point.date.isoformat() for point in series] == [
        "2011-12-28",
        "2011-12-29",
        "2011-12-30",
        "2011-12-31",
        "2012-01-01",
    ]
    assert series[2].start == series[3].start, "a skipped day has no instant of its own"


def test_the_response_model_is_typed_by_the_declarations() -> None:
    model = Sales.statistics_model()
    assert model is Sales.statistics_model()  # built once per class
    assert model.__name__ == "SalesStatisticsGroup"
    schema = model.model_json_schema()
    measures = schema["$defs"]["SalesStatisticsMeasures"]["properties"]
    dimensions = schema["$defs"]["SalesStatisticsDimensions"]["properties"]
    assert sorted(dimensions) == ["channel", "region"]
    assert sorted(measures) == ["buyers", "first_sale", "mean_units", "most_units", "revenue", "sales"]
    assert {"type": "integer"} in measures["sales"]["anyOf"]
    assert {"type": "number"} in measures["mean_units"]["anyOf"]
    assert {"format": "date-time", "type": "string"} in measures["first_sale"]["anyOf"]
    point = schema["$defs"]["SalesStatisticsPoint"]["properties"]
    assert sorted(point) == ["date", "measures", "start"]


@pytest.fixture
def client(engine):
    router = APIRouter()

    @router.get("/sales", response_model=Page[Sales.statistics_model()])
    def sale_statistics(query: StatisticsQueryDep, session: SessionDep, channel: str | None = None):
        return Sales().aggregate_page(session, query, filters={"channel": channel})

    app = create_app(
        [ModuleSpec(name="statistics", router=router, policy=Policy.default())],
        principal_provider=lambda: Principal(id=uuid.uuid4(), role=EDITOR),
    )

    def sessions():
        with WriteGuardedSession(engine) as session:
            yield session

    app.dependency_overrides[get_session] = sessions
    return TestClient(app)


def test_a_statistics_route_answers_a_typed_page(client) -> None:
    response = client.get(
        "/api/v1/statistics/sales",
        params={
            "measures": ["sales", "revenue"],
            "by": "region",
            "sort": "region",
            "bucket": "sold",
            "start": "2026-10-01",
            "end": "2026-11-30",
            "zone": AMSTERDAM,
            "step": "month",
            "limit": 2,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["total"], body["skip"], body["limit"]) == (3, 0, 2)
    north = body["items"][0]
    assert north["dimensions"] == {"region": "north", "channel": None}
    assert north["measures"]["sales"] == 3 and north["measures"]["mean_units"] is None
    assert [point["date"] for point in north["series"]] == ["2026-10-01", "2026-11-01"]
    schema = client.get("/openapi.json").json()["components"]["schemas"]
    assert "SalesStatisticsGroup" in schema and "SalesStatisticsMeasures" in schema


@pytest.mark.parametrize(
    ("params", "status", "words"),
    [
        ({"measures": "sales", "start": "2026-10-01", "end": "2026-10-31"}, 400, "names the time bucket"),
        ({"measures": "sales", "bucket": "sold", "start": "2026-10-01"}, 400, "its first and its last day"),
        ({"measures": "sales", "channel": "web", "by": "buyer_email"}, 400, "Unknown dimension"),
        ({}, 422, "measures"),
        ({"measures": ["sales"] * 17}, 422, "measures"),
        ({"measures": "Sales;drop"}, 422, "measures"),
        ({"measures": "sales", "zone": "x" * 65}, 422, "zone"),
        ({"measures": "sales", "skip": str(10**20)}, 400, "starts at row 9223372036854775807 at the latest"),
    ],
)
def test_a_statistics_route_refuses_what_it_cannot_answer(client, params: dict, status: int, words: str) -> None:
    response = client.get("/api/v1/statistics/sales", params=params)
    assert response.status_code == status, response.text
    assert words in response.text


def test_a_column_type_that_declares_no_python_type_is_typed_any() -> None:
    # TypeEngine's own python_type raises NotImplementedError for a type that does not know
    # its Python type (a decorator or NullType answers ``object`` instead, which types the
    # figure just as loosely); the response model then accepts any value for that figure.
    from types import SimpleNamespace
    from typing import Any

    from terp.core.aggregation_http import _python_type

    class Undeclared:
        @property
        def python_type(self) -> type:
            raise NotImplementedError

    assert _python_type(SimpleNamespace(type=Undeclared())) is Any  # type: ignore[arg-type]
