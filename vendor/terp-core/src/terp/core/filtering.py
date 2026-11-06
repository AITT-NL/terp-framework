"""Declared, request-scoped read filters and sorts for :class:`~terp.core.BaseService`.

``business_filters`` covers a *static* narrowing ("only active rows"). It cannot express
the other half of every real list screen: *this* caller wants the snapshots of *that*
connection, newest first. Until now the only way to do that was a hand-written ``list``
override building ``base_query().where(...)`` — a per-module, per-endpoint blob of query
construction, which is exactly where filter bugs and accidental scope widening live, and
which no rule can inspect.

So the allowance is **declared on the service**, not built at the call site::

    class CatalogSnapshotService(BaseService[Snapshot, SnapshotCreate, SnapshotUpdate]):
        model = Snapshot
        filterable = (FilterField("connection_id", Snapshot.connection_id),)
        sortable = (SortField("captured_at", Snapshot.captured_at),)
        default_sort = ("-captured_at",)

and the route passes typed values through::

    @router.get("/", response_model=Page[SnapshotRead])
    def list_snapshots(
        pagination: PaginationDep,
        session: SessionDep,
        connection_id: uuid.UUID | None = None,
        service: SnapshotService = Depends(get_service),
    ) -> Page[SnapshotRead]:
        rows, total = service.list(session, skip=..., limit=..., filters={"connection_id": connection_id})

Three properties follow, and they are the point:

* **Fail closed.** An undeclared field or sort key raises
  :class:`~terp.core.errors.ValidationFailedError` — it is never silently ignored, so a
  client can never believe a filter applied when it did not, and can never probe a
  column the service did not expose. The name is checked before the value, so a
  *misspelled* filter is caught too, rather than passing as "absent" forever.
* **No expression at the boundary.** Callers supply *values*, never operators; the
  comparison is fixed by the declaration. There is no query-language surface to inject
  into and no way to reach a column the service did not name.
* **Composed, never substituted.** Everything still lands on ``base_query()``, so row
  scope, soft delete and ``business_filters`` are applied first and cannot be dropped.

``None`` values are dropped **after** the name is checked, so an absent optional query
parameter simply means "no filter" and the route needs no branching — without letting a
typo in the forwarded dict hide behind that same allowance.

A timestamp bound must carry its UTC offset (ADR 0206): one without names no instant, so it
is refused, naming the filter and the fix, rather than compared as if it were UTC. A calendar
day names no instant either, until it names the zone whose day it is: a filter on a timestamp
declares that zone (``zone="Europe/Amsterdam"``), and then compares a day as the whole of it,
from its midnight to the next. Without one, a day is refused like a naive bound.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal, cast, get_args
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import ColumnElement, and_, or_
from sqlalchemy.orm.attributes import InstrumentedAttribute

from terp.core.errors import ValidationFailedError
from terp.core.timestamps import require_offset

FilterOp = Literal["eq", "ne", "lt", "lte", "gt", "gte", "in", "contains"]
"""The fixed comparison set. Declared per field by the service — never sent by a client."""

_LIKE_ESCAPE = "\\"


def _holds_timestamps(column: InstrumentedAttribute) -> bool:
    try:
        return issubclass(column.type.python_type, datetime)
    except NotImplementedError:  # a column type that names no Python type holds none
        return False


def _is_day(value: object) -> bool:
    return isinstance(value, date) and not isinstance(value, datetime)


def _in_range(name: str, value: object, column: InstrumentedAttribute) -> object:
    """*value*, refused when it names no instant a timestamp can hold.

    A bound with no UTC offset names no instant at all, so it is a 400 that names the
    filter and the fix (ADR 0206), and so is a calendar day on a timestamp column whose
    filter declares no zone. A bound the app's own code gives a timestamp column as text is
    read as a date and time first, as a request's would be. A caller's bound reaches the
    column's type at execution, where an offset that carries it past the years a timestamp
    holds (``0001-01-01T00:00:00+14:00``) raises inside the driver call and leaks as a 500.
    Found here, it is a 400 that names the filter. A bound that is a date and time is
    otherwise left as it is: a ``UtcDateTime`` column converts it, and a plain one compares
    it as it always did.
    """
    if (_is_day(value) or isinstance(value, str | bytes | bytearray)) and _holds_timestamps(column):
        value = require_offset(name, value)
    if isinstance(value, datetime):
        require_offset(name, value)
        try:
            value.astimezone(UTC)
        except OverflowError as exc:
            raise ValidationFailedError(
                f"Filter {name!r} is outside the range of a timestamp."
            ) from exc
    return value


def _escape_like(value: str) -> str:
    """Neutralize LIKE wildcards so a ``contains`` filter matches literal text."""
    for char in (_LIKE_ESCAPE, "%", "_"):
        value = value.replace(char, _LIKE_ESCAPE + char)
    return value


@dataclass(frozen=True)
class FilterField:
    """One column a caller may narrow a read by, and the comparison it permits."""

    name: str
    """The name the caller uses (match the route's query-parameter name)."""

    column: InstrumentedAttribute
    """The model column. Naming it here is what keeps it off the request surface."""

    op: FilterOp = "eq"
    """The fixed comparison. ``contains`` is a case-insensitive literal substring match."""

    zone: str | None = None
    """The IANA time zone a calendar day is read in, on a timestamp column (ADR 0206).

    A day then stands for the whole of it in that zone, from its midnight to the next, so
    ``eq`` is that day, ``gte`` from its start, ``lte`` through its end, ``gt`` after it,
    ``lt`` before it, and ``in`` any of the days. Without a zone, a day names no instant and
    is refused like a naive bound.
    """

    def __post_init__(self) -> None:
        if self.op not in get_args(FilterOp):
            raise ValueError(
                f"FilterField {self.name!r} declares op {self.op!r}; choose one of "
                f"{', '.join(get_args(FilterOp))}"
            )
        if self.zone is None:
            return
        if not _holds_timestamps(self.column):
            raise ValueError(
                f"FilterField {self.name!r} declares zone={self.zone!r}, which reads a calendar "
                "day against a timestamp, on a column that holds none; remove the zone"
            )
        try:
            ZoneInfo(self.zone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(
                f"FilterField {self.name!r} declares zone={self.zone!r}, which is not a time "
                "zone this server knows; name an IANA zone, for example 'Europe/Amsterdam'"
            ) from exc

    def condition(self, value: object) -> ColumnElement[bool]:
        """Build this field's SQL condition for *value*."""
        if self.op == "contains":
            if not isinstance(value, str):
                raise ValidationFailedError(f"Filter {self.name!r} expects text.")
            return self.column.ilike(f"%{_escape_like(value)}%", escape=_LIKE_ESCAPE)
        if self.op == "in":
            if not isinstance(value, (list, tuple, set, frozenset)):
                raise ValidationFailedError(f"Filter {self.name!r} expects a list of values.")
            if self.zone is not None and any(_is_day(item) for item in value):
                return or_(*(self._compare("eq", item) for item in value))
            return self.column.in_([_in_range(self.name, item, self.column) for item in value])
        return self._compare(self.op, value)

    def _compare(self, op: str, value: object) -> ColumnElement[bool]:
        column = self.column
        if self.zone is not None and _is_day(value):
            start, end = _day_in(cast("date", value), ZoneInfo(self.zone))
            if op == "eq":
                return and_(column >= start, column < end)
            if op == "ne":
                return or_(column < start, column >= end)
            # Before the day, through its end, after it, from its start: each an instant.
            op, value = {"lt": ("lt", start), "lte": ("lt", end), "gt": ("gte", end), "gte": ("gte", start)}[op]
        else:
            value = _in_range(self.name, value, column)
        if op == "eq":
            return column == value
        if op == "ne":
            return column != value
        if op == "lt":
            return column < value
        if op == "lte":
            return column <= value
        if op == "gt":
            return column > value
        return column >= value


def _day_in(day: date, zone: ZoneInfo) -> tuple[datetime, datetime]:
    """The UTC instants *day* starts and ends at in *zone*. A day daylight saving shortens or
    lengthens keeps its length, and one whose midnight it skips starts at the hour after."""
    start, end = (
        datetime.combine(edge, time(), tzinfo=zone).astimezone(UTC) for edge in (day, day + timedelta(days=1))
    )
    return start, end


@dataclass(frozen=True)
class SortField:
    """One column a caller may order a read by."""

    name: str
    """The name the caller uses; ``-name`` requests descending."""

    column: InstrumentedAttribute


def resolve_filters(
    declared: Sequence[FilterField], requested: Mapping[str, object] | None
) -> tuple[ColumnElement[bool], ...]:
    """Turn *requested* values into conditions, refusing anything undeclared.

    Every key is checked against the declaration **before** ``None`` values are
    dropped, and the order is the whole guarantee. A route forwards optional query
    parameters unbranched, so a mistyped key is ``None`` on every request that does
    not happen to set it: checking the value first would leave the typo unreachable
    *and* unraisable, the read silently wide open, and every test that omits that
    parameter still green. The name is a fact about the code, so it is validated
    even when the caller sent nothing for it.

    A declared key whose value is ``None`` is then dropped: an absent optional query
    parameter is not a filter, which is what lets the route stay branch-free.
    """
    if not requested:
        return ()
    by_name = {field.name: field for field in declared}
    conditions: list[ColumnElement[bool]] = []
    for name, value in requested.items():
        field = by_name.get(name)
        if field is None:
            allowed = ", ".join(sorted(by_name)) or "none"
            raise ValidationFailedError(
                f"Unknown filter {name!r}. Filterable fields: {allowed}."
            )
        if value is None:
            continue
        conditions.append(field.condition(value))
    return tuple(conditions)


def resolve_sort(
    declared: Sequence[SortField], requested: Sequence[str] | None
) -> tuple[ColumnElement[object], ...]:
    """Turn ``["-captured_at"]`` into ORDER BY terms, refusing anything undeclared."""
    if not requested:
        return ()
    by_name = {field.name: field for field in declared}
    terms: list[ColumnElement[object]] = []
    for key in requested:
        descending = key.startswith("-")
        name = key[1:] if descending else key
        field = by_name.get(name)
        if field is None:
            allowed = ", ".join(sorted(by_name)) or "none"
            raise ValidationFailedError(
                f"Unknown sort field {name!r}. Sortable fields: {allowed}."
            )
        terms.append(field.column.desc() if descending else field.column.asc())
    return tuple(terms)
