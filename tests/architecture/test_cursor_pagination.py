"""Keyset (cursor) pagination: ``CursorPage`` + ``BaseService.list_by_cursor`` (ADR 0064).

The scale-friendly alternative to offset pagination (review M5): pages walk the
stable ``(created_at, id)`` keyset behind an opaque cursor — no ``OFFSET`` scan —
and the exact ``COUNT(*)`` runs only when the request asks (``include_total``).
The cursor is opaque and tamper-checked: a garbled value maps to the typed
``ValidationFailedError`` (uniform 400), never a leaked 500.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Field, Session, SQLModel, create_engine

from terp.core import (
    BaseSchema,
    BaseService,
    BaseTable,
    BaseUpdateSchema,
    CursorPage,
    CursorPaginationDep,
    CursorPaginationParams,
)
from terp.core.errors import ValidationFailedError
from terp.core.pagination import decode_cursor, encode_cursor


class _Entry(BaseTable, table=True):
    __tablename__ = "cursor_pagination_entry"

    name: str = Field(max_length=50)


class _EntryCreate(BaseSchema):
    name: str


class _EntryUpdate(BaseUpdateSchema):
    name: str | None = None


class _EntryService(BaseService[_Entry, _EntryCreate, _EntryUpdate]):
    model = _Entry


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as active:
        yield active
    engine.dispose()


def _params(
    cursor: str | None = None, *, limit: int = 2, include_total: bool = False
) -> CursorPaginationParams:
    return CursorPaginationParams(cursor=cursor, limit=limit, include_total=include_total)


# --------------------------------------------------------------------------- #
# cursor codec
# --------------------------------------------------------------------------- #


def test_cursor_round_trips() -> None:
    created_at = datetime(2026, 7, 4, 12, 30, 45, 123456, tzinfo=UTC)
    entity_id = uuid.uuid4()
    assert decode_cursor(encode_cursor(created_at, entity_id)) == (created_at, entity_id)


@pytest.mark.parametrize(
    "garbled",
    [
        "not base64 !!",  # not decodable base64
        "é",  # not ASCII, so not valid URL-safe base64 cursor input
        "AAAA",  # decodable, but not a keyset payload
        encode_cursor(datetime(2026, 1, 1, tzinfo=UTC), uuid.uuid4())[:-4] + "zzz=",
        "/w==",  # valid base64, not valid UTF-8
    ],
)
def test_a_tampered_cursor_maps_to_a_typed_400(garbled: str) -> None:
    with pytest.raises(ValidationFailedError):
        decode_cursor(garbled)


# --------------------------------------------------------------------------- #
# list_by_cursor
# --------------------------------------------------------------------------- #


def test_pages_walk_the_keyset_without_overlap(session: Session) -> None:
    service = _EntryService()
    for index in range(5):
        service.create(session, _EntryCreate(name=f"row-{index}"))

    first, cursor_1, total = service.list_by_cursor(session, pagination=_params())
    assert total is None  # no COUNT unless asked (review M5)
    assert len(first) == 2 and cursor_1 is not None

    second, cursor_2, _ = service.list_by_cursor(session, pagination=_params(cursor_1))
    assert len(second) == 2 and cursor_2 is not None

    last, cursor_3, _ = service.list_by_cursor(session, pagination=_params(cursor_2))
    assert len(last) == 1
    assert cursor_3 is None  # last page

    everything = [*first, *second, *last]
    assert len({row.id for row in everything}) == 5  # no overlap, nothing skipped
    # deterministic keyset order — (created_at, id), even across equal timestamps
    assert [row.id for row in everything] == [
        row.id for row in sorted(everything, key=lambda row: (row.created_at, row.id))
    ]


def test_a_page_holding_exactly_the_remainder_is_the_last(session: Session) -> None:
    service = _EntryService()
    for index in range(2):
        service.create(session, _EntryCreate(name=f"row-{index}"))
    rows, next_cursor, _ = service.list_by_cursor(session, pagination=_params())
    assert len(rows) == 2
    assert next_cursor is None  # fetched limit+1 found no further row


def test_include_total_computes_the_scoped_count(session: Session) -> None:
    service = _EntryService()
    for index in range(3):
        service.create(session, _EntryCreate(name=f"row-{index}"))
    rows, next_cursor, total = service.list_by_cursor(
        session, pagination=_params(include_total=True)
    )
    assert total == 3
    assert len(rows) == 2 and next_cursor is not None


# --------------------------------------------------------------------------- #
# envelope + dependency
# --------------------------------------------------------------------------- #


def test_cursor_page_envelope_carries_the_request_shape() -> None:
    pagination = _params(limit=10)
    page = CursorPage[str].of(["a", "b"], pagination, next_cursor="abc", total=7)
    assert (page.items, page.next_cursor, page.limit, page.total) == (
        ["a", "b"],
        "abc",
        10,
        7,
    )
    default_total = CursorPage[str].of([], pagination, next_cursor=None)
    assert default_total.total is None


def test_cursor_pagination_dependency_defaults_are_scale_safe() -> None:
    app = FastAPI()

    @app.get("/probe")
    def probe(pagination: CursorPaginationDep) -> dict[str, object]:
        return {
            "cursor": pagination.cursor,
            "limit": pagination.limit,
            "include_total": pagination.include_total,
        }

    client = TestClient(app)
    body = client.get("/probe").json()
    assert body["cursor"] is None
    assert body["include_total"] is False  # the COUNT is opt-in
    asked = client.get("/probe", params={"cursor": "abc", "include_total": "true"}).json()
    assert (asked["cursor"], asked["include_total"]) == ("abc", True)
