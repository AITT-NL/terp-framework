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
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import ColumnElement
from sqlalchemy.orm.attributes import InstrumentedAttribute

from terp.core.errors import ValidationFailedError

FilterOp = Literal["eq", "ne", "lt", "lte", "gt", "gte", "in", "contains"]
"""The fixed comparison set. Declared per field by the service — never sent by a client."""

_LIKE_ESCAPE = "\\"


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

    def condition(self, value: object) -> ColumnElement[bool]:
        """Build this field's SQL condition for *value*."""
        if self.op == "eq":
            return self.column == value
        if self.op == "ne":
            return self.column != value
        if self.op == "lt":
            return self.column < value
        if self.op == "lte":
            return self.column <= value
        if self.op == "gt":
            return self.column > value
        if self.op == "gte":
            return self.column >= value
        if self.op == "in":
            if not isinstance(value, (list, tuple, set, frozenset)):
                raise ValidationFailedError(
                    f"Filter {self.name!r} expects a list of values."
                )
            return self.column.in_(list(value))
        if not isinstance(value, str):
            raise ValidationFailedError(f"Filter {self.name!r} expects text.")
        return self.column.ilike(f"%{_escape_like(value)}%", escape=_LIKE_ESCAPE)


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
