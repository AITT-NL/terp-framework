"""Declared request-scoped filters and sorts (``filterable`` / ``sortable``).

The alternative this replaces is a hand-written ``list`` override assembling
``where`` clauses per endpoint — the place filter bugs and accidental scope widening
live, and which no rule can inspect. Declaring the allowance on the service makes the
read surface enumerable and fail-closed. These tests pin the three properties that
make it safe: an undeclared name is *refused* (never ignored), the caller supplies
values rather than operators, and everything still composes on the non-droppable
``base_query()``.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence

import pytest
from sqlalchemy import ColumnElement
from sqlmodel import Field, Session, SQLModel, create_engine

from terp.core import (
    BaseSchema,
    BaseService,
    BaseTable,
    BaseUpdateSchema,
    FilterField,
    SoftDeleteMixin,
    SortField,
)
from terp.core.errors import ValidationFailedError


class _Item(BaseTable, SoftDeleteMixin, table=True):
    __tablename__ = "declared_filter_item"

    name: str = Field(max_length=50)
    status: str = Field(max_length=20, default="open")
    rank: int = Field(default=0)


class _ItemCreate(BaseSchema):
    name: str
    status: str = "open"
    rank: int = 0


class _ItemUpdate(BaseUpdateSchema):
    name: str | None = None


class _ItemService(BaseService[_Item, _ItemCreate, _ItemUpdate]):
    model = _Item

    filterable = (
        FilterField("status", _Item.status),
        FilterField("not_status", _Item.status, op="ne"),
        FilterField("below_rank", _Item.rank, op="lt"),
        FilterField("max_rank", _Item.rank, op="lte"),
        FilterField("above_rank", _Item.rank, op="gt"),
        FilterField("min_rank", _Item.rank, op="gte"),
        FilterField("q", _Item.name, op="contains"),
        FilterField("status_in", _Item.status, op="in"),
    )
    sortable = (SortField("rank", _Item.rank), SortField("name", _Item.name))


class _OpenOnlyService(_ItemService):
    """A service whose static narrowing must survive any caller-supplied filter."""

    def business_filters(self) -> Sequence[ColumnElement[bool]]:
        return (_Item.status == "open",)


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as active:
        yield active
    engine.dispose()


@pytest.fixture
def service(session: Session) -> _ItemService:
    made = _ItemService()
    made.create(session, _ItemCreate(name="alpha", status="open", rank=3))
    made.create(session, _ItemCreate(name="beta", status="closed", rank=1))
    made.create(session, _ItemCreate(name="gamma 50%", status="open", rank=2))
    return made


def test_no_filter_is_the_full_scoped_list(
    session: Session, service: _ItemService
) -> None:
    rows, total = service.list(session, skip=0, limit=100)
    assert total == 3
    assert len(rows) == 3


def test_declared_filter_narrows(session: Session, service: _ItemService) -> None:
    rows, total = service.list(session, skip=0, limit=100, filters={"status": "open"})
    assert total == 2
    assert {row.name for row in rows} == {"alpha", "gamma 50%"}


def test_none_values_are_dropped(session: Session, service: _ItemService) -> None:
    # A route forwards its optional query parameters straight through — an absent one
    # means "no filter", so the route needs no branching.
    rows, total = service.list(session, skip=0, limit=100, filters={"status": None})
    assert total == 3
    assert len(rows) == 3


def test_comparison_operators(session: Session, service: _ItemService) -> None:
    _, total = service.list(session, skip=0, limit=100, filters={"min_rank": 2})
    assert total == 2
    _, total = service.list(
        session, skip=0, limit=100, filters={"status_in": ["open", "closed"]}
    )
    assert total == 3


def test_every_declared_comparison_narrows_the_way_it_reads(
    session: Session, service: _ItemService
) -> None:
    # Rows are alpha (open, 3), beta (closed, 1) and "gamma 50%" (open, 2). Each op is
    # pinned here because the service picks it and the caller cannot: a comparison that
    # quietly behaved like another one would widen a read nobody reviewed.
    def _total(**filters: object) -> int:
        return service.list(session, skip=0, limit=100, filters=filters)[1]

    assert _total(not_status="open") == 1
    assert _total(below_rank=2) == 1
    assert _total(max_rank=2) == 2
    assert _total(above_rank=2) == 1


def test_a_value_of_the_wrong_shape_is_refused_rather_than_coerced(
    session: Session, service: _ItemService
) -> None:
    # "in" over a bare string would iterate its characters and "contains" over a number
    # would stringify it — both silently answer a question nobody asked.
    with pytest.raises(ValidationFailedError, match="list of values"):
        service.list(session, skip=0, limit=100, filters={"status_in": "open"})
    with pytest.raises(ValidationFailedError, match="expects text"):
        service.list(session, skip=0, limit=100, filters={"q": 50})


def test_contains_matches_wildcards_literally(
    session: Session, service: _ItemService
) -> None:
    # "%" is data, not a pattern: a caller cannot turn a substring search into a
    # match-everything probe.
    _, total = service.list(session, skip=0, limit=100, filters={"q": "50%"})
    assert total == 1
    _, total = service.list(session, skip=0, limit=100, filters={"q": "%"})
    assert total == 1  # matches only the literal '%', not all three rows


def test_undeclared_filter_is_refused_not_ignored(
    session: Session, service: _ItemService
) -> None:
    # Silently ignoring it would let a caller believe a narrowing applied when the read
    # was wide open — and would let them probe for columns the service never exposed.
    with pytest.raises(ValidationFailedError) as raised:
        service.list(session, skip=0, limit=100, filters={"rank": 1})
    assert "rank" in str(raised.value)


def test_undeclared_sort_is_refused(session: Session, service: _ItemService) -> None:
    with pytest.raises(ValidationFailedError):
        service.list(session, skip=0, limit=100, sort=["-secret_column"])


def test_sort_is_applied_in_both_directions(
    session: Session, service: _ItemService
) -> None:
    rows, _ = service.list(session, skip=0, limit=100, sort=["rank"])
    assert [row.rank for row in rows] == [1, 2, 3]
    rows, _ = service.list(session, skip=0, limit=100, sort=["-rank"])
    assert [row.rank for row in rows] == [3, 2, 1]


def test_default_sort_applies_when_the_caller_asks_for_none(
    session: Session, service: _ItemService
) -> None:
    class _RankedService(_ItemService):
        default_sort = ("-rank",)

    rows, _ = _RankedService().list(session, skip=0, limit=100)
    assert [row.rank for row in rows] == [3, 2, 1]


def test_filters_cannot_widen_past_scope_or_business_filters(
    session: Session, service: _ItemService
) -> None:
    # The caller asks for closed rows on a service that statically serves only open
    # ones: conditions compose (AND), so the answer is empty — never the closed row.
    restricted = _OpenOnlyService()
    rows, total = restricted.list(
        session, skip=0, limit=100, filters={"status": "closed"}
    )
    assert (rows, total) == ([], 0)


def test_filters_do_not_resurrect_soft_deleted_rows(
    session: Session, service: _ItemService
) -> None:
    rows, _ = service.list(session, skip=0, limit=100, filters={"status": "closed"})
    service.delete(session, rows[0].id)
    _, total = service.list(session, skip=0, limit=100, filters={"status": "closed"})
    assert total == 0


def test_cursor_pagination_accepts_the_same_filters(
    session: Session, service: _ItemService
) -> None:
    from terp.core.pagination import CursorPaginationParams

    rows, _, total = service.list_by_cursor(
        session,
        pagination=CursorPaginationParams(limit=50, cursor=None, include_total=True),
        filters={"status": "open"},
    )
    assert total == 2
    assert {row.name for row in rows} == {"alpha", "gamma 50%"}
