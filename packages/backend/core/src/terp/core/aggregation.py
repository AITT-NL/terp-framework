"""Declared statistics over a scoped read: measures, dimensions and time buckets (ADR 0204).

A list narrows and orders the rows its service declared it may (:mod:`terp.core.filtering`); a
statistic counts and sums them, declared the same way, beside ``filterable`` and ``sortable``::

    class InvoiceService(BaseService[Invoice, InvoiceCreate, InvoiceUpdate]):
        model = Invoice
        measures = (Measure("invoices"), Measure("revenue", Invoice.amount, op="sum"))
        dimensions = (Dimension("status", Invoice.status),)
        time_buckets = (TimeBucket("issued", Invoice.issued_at),)

A route takes :data:`~terp.core.aggregation_http.StatisticsQueryDep` and returns
``InvoiceService().aggregate_page(session, query)`` as ``Page[InvoiceService.statistics_model()]``.
The rows are the scoped query's, narrowed by the declared filters inside a subquery and grouped
by plain columns outside it, so row scope cannot be dropped. Everything undeclared is refused,
every result is capped, and a statistic never answers for one person's personal data.
``terp guide aggregates`` walks through it.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel
from sqlalchemy import Integer, and_, distinct, func, literal, or_, union_all
from sqlalchemy import select as sa_select
from sqlalchemy.orm.attributes import InstrumentedAttribute
from sqlmodel import Session, select
from sqlmodel.sql.expression import SelectOfScalar

from terp.core.errors import ValidationFailedError
from terp.core.filtering import FilterField, resolve_filters
from terp.core.aggregation_window import _steps_table, window_bounds, window_steps
from terp.core.pagination import refuse_skip_past_any_table
from terp.core.personal_reads import personal_reads

MeasureOp = Literal["count", "count_distinct", "sum", "avg", "min", "max"]
"""The fixed aggregate set. Declared per measure by the service — never sent by a client."""

TimeStep = Literal["day", "week", "month"]
"""Calendar steps of the caller's time zone. A week starts on Monday (ISO 8601)."""

#: The ops whose answer is derived from the values themselves. Over a group of one, each
#: of them is that one row's value, so none may run over a field declared personal.
VALUE_OPS: frozenset[str] = frozenset({"sum", "avg", "min", "max"})

#: How many groups one page may hold unless a declaration lowers it.
DEFAULT_MAX_GROUPS = 100

#: How many buckets one series may hold unless a time bucket lowers or raises it.
DEFAULT_MAX_BUCKETS = 366

#: How many series points one page may carry, groups times steps: 100 groups of a year of
#: days would be 36,600 points, megabytes no screen draws.
DEFAULT_MAX_POINTS = 10_000

_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

MeasureValue = int | float | Decimal | dt.date | dt.datetime | None
DimensionValue = str | int | float | bool | Decimal | dt.date | dt.datetime | None


@dataclass(frozen=True)
class Measure:
    """One figure a caller may ask for, and the aggregate that computes it."""

    name: str
    column: InstrumentedAttribute | None = None
    op: MeasureOp = "count"

    def __post_init__(self) -> None:
        if not _NAME.match(self.name):
            raise TypeError(f"Measure name {self.name!r} must be lower_snake_case.")
        if self.op != "count" and self.column is None:
            raise TypeError(f"Measure {self.name!r} ({self.op}) needs the column it aggregates.")


@dataclass(frozen=True)
class Dimension:
    """One column a caller may group by: its own values, no expression."""

    name: str
    column: InstrumentedAttribute

    def __post_init__(self) -> None:
        if not _NAME.match(self.name):
            raise TypeError(f"Dimension name {self.name!r} must be lower_snake_case.")


@dataclass(frozen=True)
class TimeBucket:
    """A timestamp a caller may window rows by, and place in calendar steps of a zone."""

    name: str
    column: InstrumentedAttribute
    steps: tuple[TimeStep, ...] = ("day", "week", "month")
    max_buckets: int = DEFAULT_MAX_BUCKETS

    def __post_init__(self) -> None:
        if not _NAME.match(self.name):
            raise TypeError(f"Time bucket name {self.name!r} must be lower_snake_case.")
        if not self.steps:
            raise TypeError(f"Time bucket {self.name!r} declares no step.")


@dataclass(frozen=True)
class Window:
    """The calendar dates ``start`` to ``end`` (both included) of *zone*, on one time bucket.

    Rows outside the window are left out of every figure. With a ``step``, each group also
    carries its series: one point per calendar step, the first starting at ``start`` and the
    last ending after ``end``, so a series may begin or end part way through a week or month.
    """

    bucket: str
    start: dt.date
    end: dt.date
    zone: str | ZoneInfo
    step: TimeStep | None = None


class SeriesPoint(BaseModel):
    """One step of a group's series: when it starts, the calendar date it is, and its figures.

    ``date`` is the step's own label. ``start`` is the instant, in the window's zone, and on a
    day whose midnight daylight saving skips it reads 01:00; a client that re-zones it to its
    own clock could also move it to the day before, so label a step by ``date``.
    """

    start: dt.datetime
    date: dt.date
    measures: dict[str, MeasureValue]


class AggregateGroup(BaseModel):
    """One combination of the requested dimensions, its figures, and its series if asked."""

    dimensions: dict[str, DimensionValue]
    measures: dict[str, MeasureValue]
    series: list[SeriesPoint] | None = None


@dataclass(frozen=True)
class Statistics:
    """What a read may be counted and summed by: the declarations, in one value."""

    measures: Sequence[Measure]
    dimensions: Sequence[Dimension] = ()
    time_buckets: Sequence[TimeBucket] = ()
    filterable: Sequence[FilterField] = ()
    max_groups: int = DEFAULT_MAX_GROUPS
    max_points: int = DEFAULT_MAX_POINTS

    def __post_init__(self) -> None:
        refusal = declaration_refusal(
            self.measures, self.dimensions, self.time_buckets, owner="Statistics"
        )
        if refusal:
            raise TypeError(refusal)


def declaration_refusal(
    measures: Sequence[Measure],
    dimensions: Sequence[Dimension],
    time_buckets: Sequence[TimeBucket],
    *,
    owner: str,
) -> str:
    """Why these declarations are refused, or ``""``. Checked when a class is defined.

    A name is the caller's key and the response's, so the three kinds share one namespace. A
    grouping, a time bucket or a value-derived measure over a field declared personal is
    refused: over a group of one each of them is that person's value, and a breakdown per
    person is a list, which has a route, a policy and a page of its own (ADR 0204 decision 5).
    """
    names = [m.name for m in measures] + [d.name for d in dimensions] + [b.name for b in time_buckets]
    doubled = sorted({n for n in names if names.count(n) > 1})
    if doubled:
        return f"{owner} declares {', '.join(map(repr, doubled))} more than once among its statistics."
    for dimension in dimensions:
        reads = personal_reads(dimension.column)
        if reads:
            return (
                f"{owner} groups by {dimension.name!r}, {reads}: a group of one is that person's "
                "value. A breakdown per person is a list route, not a statistic."
            )
    for bucket in time_buckets:
        reads = personal_reads(bucket.column)
        if reads:
            return (
                f"{owner} buckets by {bucket.name!r}, {reads}: a bucket of one is that person's "
                "value. Count it, or list it, but do not bucket it."
            )
    for measure in measures:
        reads = personal_reads(measure.column) if measure.op in VALUE_OPS and measure.column is not None else ""
        if reads:
            return (
                f"{owner} declares {measure.name!r} as {measure.op} over {reads}: over a group of "
                "one it is that person's value. Only count and count_distinct may run over "
                "personal data."
            )
    return ""


def resolve_time_zone(name: str | ZoneInfo) -> ZoneInfo:
    """The IANA time zone *name* names, or a validation failure that says which name it was."""
    if isinstance(name, ZoneInfo):
        return name
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValidationFailedError(f"{name!r} is not a time zone this server knows.") from exc


def _by_name(declared: Sequence[Any], requested: Sequence[str], kind: str) -> list[Any]:
    known = {item.name: item for item in declared}
    twice = sorted({name for name in requested if list(requested).count(name) > 1})
    if twice:
        raise ValidationFailedError(f"Ask for each {kind} once; {', '.join(map(repr, twice))} came twice.")
    chosen = []
    for name in requested:
        item = known.get(name)
        if item is None:
            allowed = ", ".join(sorted(known)) or "none"
            raise ValidationFailedError(f"Unknown {kind} {name!r}. Declared {kind}s: {allowed}.")
        chosen.append(item)
    return chosen


def _aggregate(measure: Measure, source: Any) -> Any:
    if measure.op == "count":
        return func.count()
    column = source.c[f"v_{measure.name}"]
    if measure.op == "count_distinct":
        return func.count(distinct(column))
    return getattr(func, measure.op)(column)


def _empty(measure: Measure) -> MeasureValue:
    """A step with no rows: zero for what counts or adds, nothing for the rest."""
    return 0 if measure.op in ("count", "count_distinct", "sum") else None


def _value(measure: Measure, raw: Any) -> MeasureValue:
    if raw is None:
        return _empty(measure)
    if measure.op == "avg":
        return float(raw)
    return raw


def aggregate(
    session: Session,
    query: SelectOfScalar[Any],
    statistics: Statistics,
    *,
    measures: Sequence[str],
    by: Sequence[str] = (),
    window: Window | None = None,
    filters: Mapping[str, object] | None = None,
    sort: Sequence[str] | None = None,
    skip: int = 0,
    limit: int | None = None,
) -> tuple[list[AggregateGroup], int]:
    """One page of groups over *query*'s rows, and how many groups there are in all.

    *query* is the scoped read the figures are taken from — a service's ``base_query()``.
    """
    chosen = _by_name(statistics.measures, measures, "measure")
    if not chosen:
        raise ValidationFailedError("Ask for at least one measure.")
    groups_by = _by_name(statistics.dimensions, by, "dimension")
    limit = statistics.max_groups if limit is None else limit
    if skip < 0:
        raise ValidationFailedError(f"A page of groups starts at 0 or later; {skip} was asked.")
    refuse_skip_past_any_table(skip)
    if limit < 1 or limit > statistics.max_groups:
        raise ValidationFailedError(
            f"A page of groups holds 1 to {statistics.max_groups}; {limit} was asked."
        )
    bucket: TimeBucket | None = None
    bounds: list[dt.datetime] = []
    zone: ZoneInfo | None = None
    if window is not None:
        (bucket,) = _by_name(statistics.time_buckets, [window.bucket], "time bucket")
        if window.step is not None and window.step not in bucket.steps:
            raise ValidationFailedError(
                f"Time bucket {bucket.name!r} steps by {', '.join(bucket.steps)}, not {window.step!r}."
            )
        zone = resolve_time_zone(window.zone)
        try:
            steps = window_steps(window)
        except OverflowError as exc:
            raise ValidationFailedError("That window reaches past the years a timestamp holds.") from exc
        if window.step is not None and steps > bucket.max_buckets:
            raise ValidationFailedError(
                f"That window holds {steps} {window.step}s; a series holds at most "
                f"{bucket.max_buckets}. Ask for a shorter window or a longer step."
            )
        if window.step is not None and steps * limit > statistics.max_points:
            raise ValidationFailedError(
                f"{limit} groups of {steps} {window.step}s would be {steps * limit} points; a "
                f"page carries at most {statistics.max_points}. Ask for fewer groups, a "
                "shorter window or a longer step."
            )
        try:
            bounds = window_bounds(window, zone)
        except OverflowError as exc:
            raise ValidationFailedError("That window reaches past the years a timestamp holds.") from exc

    declared_filters = {field.name: field for field in statistics.filterable}
    for name, value in (filters or {}).items():
        field = declared_filters.get(name)
        reads = personal_reads(field.column) if value is not None and field is not None else ""
        if reads:
            raise ValidationFailedError(
                f"Filter {name!r} narrows by {reads}, and a statistic is never narrowed by one: "
                "its counts would answer for one person."
            )
    scoped = query
    conditions = resolve_filters(statistics.filterable, filters)
    if conditions:
        scoped = scoped.where(*conditions)
    columns: list[Any] = [d.column.label(f"d_{d.name}") for d in groups_by]
    columns += [m.column.label(f"v_{m.name}") for m in chosen if m.column is not None]
    if bucket is not None:
        scoped = scoped.where(bucket.column >= bounds[0], bucket.column < bounds[-1])
        if window is not None and window.step is not None:
            steps_table = _steps_table(bounds, bucket.column.type)
            scoped = scoped.join(
                steps_table,
                and_(bucket.column >= steps_table.c.lo, bucket.column < steps_table.c.hi),
            )
            columns.append(steps_table.c.i.label("b"))
    # A count alone over no dimension projects no column of the model, so the FROM is
    # kept explicitly: projecting a literal would otherwise drop it and count one row.
    rows = scoped.with_only_columns(
        *(columns or [literal(1).label("one")]), maintain_column_froms=True
    ).subquery()

    keys = [rows.c[f"d_{d.name}"] for d in groups_by]
    figures = [_aggregate(m, rows).label(f"m_{m.name}") for m in chosen]
    # Explicitly from the rows: a bare count() names no column of them and would read none.
    grouped = sa_select(*keys, *figures).select_from(rows)
    if keys:
        grouped = grouped.group_by(*keys)
    total = (
        int(session.exec(select(func.count()).select_from(grouped.subquery())).one())
        if keys
        else 1
    )
    order = _order(sort, chosen, groups_by, figures, keys)
    page = session.exec(grouped.order_by(*order).offset(skip).limit(limit)).mappings().all()

    result: list[AggregateGroup] = []
    for mapping in page:
        result.append(
            AggregateGroup(
                dimensions={d.name: mapping[f"d_{d.name}"] for d in groups_by},
                measures={m.name: _value(m, mapping[f"m_{m.name}"]) for m in chosen},
            )
        )
    if window is not None and window.step is not None and result:
        _attach_series(session, rows, chosen, groups_by, keys, result, bounds, zone)
    return result, total


def _order(sort, chosen, groups_by, figures, keys) -> list[Any]:
    by_name = {m.name: f for m, f in zip(chosen, figures, strict=True)}
    by_name.update({d.name: k for d, k in zip(groups_by, keys, strict=True)})
    requested = list(sort or ([f"-{chosen[0].name}"] if keys else []))
    terms: list[Any] = []
    for item in requested:
        descending = item.startswith("-")
        name = item[1:] if descending else item
        term = by_name.get(name)
        if term is None:
            allowed = ", ".join(sorted(by_name)) or "none"
            raise ValidationFailedError(f"Unknown sort key {name!r}. Sortable here: {allowed}.")
        terms.append(term.desc().nulls_last() if descending else term.asc().nulls_last())
    # The dimensions break every tie, so a page boundary never repeats or drops a group.
    terms += [key.asc().nulls_last() for key in keys]
    return terms


def _attach_series(session, rows, chosen, groups_by, keys, result, bounds, zone) -> None:
    index = rows.c["b"]
    figures = [_aggregate(m, rows).label(f"m_{m.name}") for m in chosen]
    query = sa_select(*keys, index, *figures).select_from(rows).group_by(*keys, index)
    if keys:
        query = query.where(
            or_(
                *(
                    and_(
                        *(
                            key.is_(None) if group.dimensions[d.name] is None else key == group.dimensions[d.name]
                            for d, key in zip(groups_by, keys, strict=True)
                        )
                    )
                    for group in result
                )
            )
        )
    found: dict[tuple, dict[int, Any]] = {}
    for mapping in session.exec(query).mappings().all():
        group_key = tuple(mapping[f"d_{d.name}"] for d in groups_by)
        found.setdefault(group_key, {})[int(mapping["b"])] = mapping
    starts = [bound.astimezone(zone) for bound in bounds[:-1]]
    for group in result:
        steps = found.get(tuple(group.dimensions[d.name] for d in groups_by), {})
        group.series = [
            SeriesPoint(
                start=start,
                date=start.date(),
                measures={
                    m.name: _value(m, steps[i][f"m_{m.name}"]) if i in steps else _empty(m)
                    for m in chosen
                },
            )
            for i, start in enumerate(starts)
        ]


__all__ = [
    "aggregate",
    "AggregateGroup",
    "declaration_refusal",
    "DEFAULT_MAX_BUCKETS",
    "DEFAULT_MAX_GROUPS",
    "DEFAULT_MAX_POINTS",
    "Dimension",
    "Measure",
    "MeasureOp",
    "resolve_time_zone",
    "SeriesPoint",
    "Statistics",
    "TimeBucket",
    "TimeStep",
    "VALUE_OPS",
    "Window",
    "window_bounds",
]
