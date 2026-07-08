"""Shared ``skip`` / ``limit`` pagination primitives with hard caps.

List endpoints are required to paginate (no unbounded queries): the architecture
gate rejects a bare ``response_model=list[...]`` / ``list`` and expects the capped
``Page[T]`` envelope with this dependency::

    @router.get("/items", response_model=ItemsPage)
    def list_items(pagination: PaginationDep, session: SessionDep) -> ItemsPage:
        ...

For large tables, the **keyset (cursor) alternative** avoids the two costs of
offset pagination — the mandatory exact ``COUNT(*)`` per page and the
``OFFSET N`` scan (ADR 0064): a route takes :data:`CursorPaginationDep` and
returns :class:`CursorPage[T]`; the total is computed **only** when the caller
asks (``include_total=true``), and the next page starts *after* an opaque
cursor over the stable ``(created_at, id)`` keyset instead of skipping rows::

    @router.get("/items/feed", response_model=ItemsCursorPage)
    def feed(pagination: CursorPaginationDep, session: SessionDep) -> ItemsCursorPage:
        rows, next_cursor, total = service.list_by_cursor(session, pagination=pagination)
        ...
"""

from __future__ import annotations

import base64
import binascii
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Generic, TypeVar

from fastapi import Depends, Query
from pydantic import BaseModel, ConfigDict

from terp.core.config import settings
from terp.core.errors import ValidationFailedError

_T = TypeVar("_T")


@dataclass(frozen=True)
class PaginationParams:
    """A validated ``skip`` + ``limit`` pair."""

    skip: int
    limit: int


def _pagination_dep(
    skip: int = Query(0, ge=0, description="Rows to skip."),
    limit: int = Query(
        settings.PAGINATION_DEFAULT_LIMIT,
        ge=1,
        le=settings.PAGINATION_MAX_LIMIT,
        description="Maximum rows to return.",
    ),
) -> PaginationParams:
    return PaginationParams(skip=skip, limit=limit)


PaginationDep = Annotated[PaginationParams, Depends(_pagination_dep)]


class Page(BaseModel, Generic[_T]):
    """A generic paginated response envelope: ``{items, total, skip, limit}``.

    Use as a route ``response_model`` so list endpoints share one shape::

        @router.get("/", response_model=Page[NoteRead])
        def list_notes(...) -> Page[NoteRead]:
            rows, total = service.list(...)
            return Page[NoteRead].of(rows, total, pagination)
    """

    model_config = ConfigDict(from_attributes=True)

    items: list[_T]
    total: int
    skip: int
    limit: int

    @classmethod
    def of(
        cls, items: list[_T], total: int, pagination: PaginationParams
    ) -> Page[_T]:
        """Build a page from rows + total + the request's pagination params."""
        return cls(
            items=list(items),
            total=total,
            skip=pagination.skip,
            limit=pagination.limit,
        )


# --------------------------------------------------------------------------- #
# Keyset (cursor) pagination — ADR 0064
# --------------------------------------------------------------------------- #

_CURSOR_SEPARATOR = "|"


def encode_cursor(created_at: datetime, entity_id: uuid.UUID) -> str:
    """Encode a row's ``(created_at, id)`` keyset position as an opaque cursor.

    URL-safe base64 of ``"<created_at isoformat>|<id>"`` — opaque to the client
    (never parsed, only echoed back), stable across requests, and holding no
    secret (both values are already serialized on the row itself).
    """
    raw = f"{created_at.isoformat()}{_CURSOR_SEPARATOR}{entity_id}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    """Decode an opaque cursor back into its ``(created_at, id)`` keyset position.

    A garbled / tampered cursor raises the typed
    :class:`~terp.core.errors.ValidationFailedError` (a uniform 400 envelope),
    never a leaked 500.
    """
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        created_at_text, _, id_text = raw.partition(_CURSOR_SEPARATOR)
        return datetime.fromisoformat(created_at_text), uuid.UUID(id_text)
    except (ValueError, binascii.Error, UnicodeDecodeError, UnicodeEncodeError) as exc:
        raise ValidationFailedError("The pagination cursor is invalid.") from exc


@dataclass(frozen=True)
class CursorPaginationParams:
    """A validated ``cursor`` + ``limit`` + ``include_total`` triple."""

    cursor: str | None
    limit: int
    include_total: bool


def _cursor_pagination_dep(
    cursor: str | None = Query(
        None, description="Opaque cursor: return rows after this position."
    ),
    limit: int = Query(
        settings.PAGINATION_DEFAULT_LIMIT,
        ge=1,
        le=settings.PAGINATION_MAX_LIMIT,
        description="Maximum rows to return.",
    ),
    include_total: bool = Query(
        False,
        description="Compute the exact total (a COUNT) — off by default at scale.",
    ),
) -> CursorPaginationParams:
    return CursorPaginationParams(cursor=cursor, limit=limit, include_total=include_total)


CursorPaginationDep = Annotated[CursorPaginationParams, Depends(_cursor_pagination_dep)]


class CursorPage(BaseModel, Generic[_T]):
    """A keyset-paginated response envelope: ``{items, next_cursor, limit, total}``.

    ``next_cursor`` is ``None`` on the last page; ``total`` is present only when
    the request asked for it (``include_total=true``) — the default omits the
    ``COUNT(*)`` entirely (review M5). Use as a route ``response_model``::

        @router.get("/feed", response_model=CursorPage[NoteRead])
        def feed(...) -> CursorPage[NoteRead]:
            rows, next_cursor, total = service.list_by_cursor(session, pagination=pagination)
            return CursorPage[NoteRead].of(rows, pagination, next_cursor=next_cursor, total=total)
    """

    model_config = ConfigDict(from_attributes=True)

    items: list[_T]
    next_cursor: str | None
    limit: int
    total: int | None = None

    @classmethod
    def of(
        cls,
        items: list[_T],
        pagination: CursorPaginationParams,
        *,
        next_cursor: str | None,
        total: int | None = None,
    ) -> CursorPage[_T]:
        """Build a cursor page from rows + the request's pagination params."""
        return cls(
            items=list(items),
            next_cursor=next_cursor,
            limit=pagination.limit,
            total=total,
        )


__all__ = [
    "CursorPage",
    "CursorPaginationDep",
    "CursorPaginationParams",
    "Page",
    "PaginationDep",
    "PaginationParams",
    "decode_cursor",
    "encode_cursor",
]
