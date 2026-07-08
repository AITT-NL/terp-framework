"""``tasks`` table model — ``BaseTable`` + opt-in ``SoftDeleteMixin`` + ``ActorStampedMixin``."""

from __future__ import annotations

from sqlmodel import Field

from terp.core import ActorStampedMixin, BaseTable, SoftDeleteMixin


class Task(BaseTable, SoftDeleteMixin, ActorStampedMixin, table=True):
    """A task. Composes two opt-in traits, each auto-honored by ``BaseService``.

    ``SoftDeleteMixin`` (``deleted_at``) makes ``delete`` a soft-delete and hides
    the row from reads (ADR 0010); ``ActorStampedMixin`` stamps the request actor
    into ``created_by_id`` / ``modified_by_id`` (ADR 0012). The two compose with
    zero module code — a soft-delete rides the audited ``_save`` chokepoint, so it
    also records *who* deleted via ``modified_by_id``.
    """

    __tablename__ = "task"

    title: str = Field(max_length=200, index=True)
    status: str = Field(default="open", max_length=20, index=True)
