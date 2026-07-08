"""The append-only audit log table — the durable record behind the core seam.

A row is one immutable fact: *actor* performed *action* on *target* during request
*request_id*, at *created_at*. It is written **only** by
:func:`terp.capabilities.audit.sink.persist_audit` (the sink ``create_app`` wires
into the core audit seam) and never updated or deleted, so it can answer "who did
what, when" long after the fact.

Append-only by design, it composes :class:`~terp.core.UUIDPrimaryKeyMixin` rather
than ``BaseTable``: there is no ``updated_at`` (rows never change) and no
optimistic-concurrency ``version`` (there is no concurrent write to a row). The
``action`` column is a plain string (the :class:`~terp.core.AuditAction` value) so
this low-layer capability needs no higher-layer enum.

``actor_id`` is an FK-less UUID on purpose: like the access capability's grant,
this leaf must not import the higher-layer user table it references, so it stays
something everything above it can depend on (never the reverse).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime
from sqlmodel import Column, Field, SQLModel

from terp.core import UUIDPrimaryKeyMixin


def _utc_now() -> datetime:
    """UTC ``now`` provider for this non-``BaseTable`` append-only row."""
    return datetime.now(UTC)


class AuditEvent(UUIDPrimaryKeyMixin, SQLModel, table=True):  # arch-allow-table-models-use-base-table: append-only audit log has no updated_at/version by design (see module docstring)
    __tablename__ = "audit_event"

    action: str = Field(max_length=16, index=True)
    target_type: str = Field(max_length=128, index=True)
    target_id: str = Field(max_length=128, index=True)
    actor_id: uuid.UUID | None = Field(default=None, index=True)
    request_id: str | None = Field(default=None, max_length=64, index=True)
    payload: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(
        default_factory=_utc_now,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
        nullable=False,
        index=True,
    )


__all__ = ["AuditEvent"]
