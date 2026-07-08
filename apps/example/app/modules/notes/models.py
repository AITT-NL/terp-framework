"""``notes`` table model — composes the kernel ``BaseTable`` (UUID + timestamps + OCC)."""

from __future__ import annotations

from sqlmodel import Field

from terp.core import ActorStampedMixin, BaseTable


class Note(BaseTable, ActorStampedMixin, table=True):
    """A simple note. ``id`` / ``created_at`` / ``updated_at`` / ``version`` are inherited.

    Composes :class:`~terp.core.ActorStampedMixin`, so ``BaseService`` stamps the
    request actor into ``created_by_id`` / ``modified_by_id`` automatically (ADR
    0012) — the module writes no stamping code.
    """

    __tablename__ = "note"

    title: str = Field(max_length=200, index=True)
    body: str = Field(default="", max_length=10_000)
