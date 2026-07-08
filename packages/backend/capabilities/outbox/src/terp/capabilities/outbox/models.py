"""The durable outbox table — one row per post-commit unit of delivery.

A row is one piece of work the framework promised to deliver *after* the
producing transaction committed: a queued background **job** (``kind="job"``) or a
domain **event** (``kind="event"``). It is written **transactionally, on the
business write's own session** (see :mod:`terp.capabilities.outbox.store`), so the
row commits atomically with the mutation that produced it and a rollback drops both
— the no-dual-write guarantee the dispatcher seam (ADR 0008) was designed for.

Append-only + status updates only: a row is inserted ``pending`` and then only ever
transitions ``pending -> dispatched`` (delivered) or ``pending -> dead_lettered``
(failed ``max_attempts`` times); its ``payload`` (the serialized envelope) never
changes. Like :class:`~terp.capabilities.audit.AuditEvent` it therefore composes
:class:`~terp.core.UUIDPrimaryKeyMixin` rather than ``BaseTable`` — there is no
optimistic-concurrency ``version`` (the lease, not OCC, arbitrates concurrent
workers) and no ``updated_at`` (the explicit ``dispatched_at`` / ``dead_lettered_at``
stamps are the meaningful timeline). Every caller-influenceable ``str`` column caps
its length so an oversized payload can never break the INSERT.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Final

from sqlalchemy import JSON, DateTime
from sqlmodel import Column, Field, SQLModel

from terp.core import UUIDPrimaryKeyMixin

# The two kinds of work the outbox carries (a plain str column, never a higher-layer
# enum — this leaf stays dependency-light, like AuditEvent.action).
KIND_EVENT: Final[str] = "event"
KIND_JOB: Final[str] = "job"

# The lifecycle a row moves through: inserted ``pending``, then terminally either
# ``dispatched`` (delivered) or ``dead_lettered`` (failed past its retry budget).
STATUS_PENDING: Final[str] = "pending"
STATUS_DISPATCHED: Final[str] = "dispatched"
STATUS_DEAD_LETTERED: Final[str] = "dead_lettered"

# Hard caps so a hostile / oversized value can never break the INSERT or the trail.
_NAME_MAX: Final[int] = 200
_KEY_MAX: Final[int] = 200
_LOCK_MAX: Final[int] = 128
_ERROR_MAX: Final[int] = 2000


def _utc_now() -> datetime:
    """UTC ``now`` provider for this non-``BaseTable`` append-only row."""
    return datetime.now(UTC)


class OutboxMessage(UUIDPrimaryKeyMixin, SQLModel, table=True):  # arch-allow-table-models-use-base-table: append-only delivery infra (like AuditEvent) — the lease, not OCC version/updated_at, arbitrates writers (see module docstring)
    __tablename__ = "outbox_message"

    kind: str = Field(max_length=8, index=True)  # KIND_EVENT | KIND_JOB
    name: str = Field(max_length=_NAME_MAX, index=True)
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    idempotency_key: str | None = Field(default=None, max_length=_KEY_MAX, index=True)
    status: str = Field(default=STATUS_PENDING, max_length=16, index=True)
    attempts: int = Field(default=0)
    available_at: datetime = Field(
        default_factory=_utc_now,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
        nullable=False,
        index=True,
    )
    locked_by: str | None = Field(default=None, max_length=_LOCK_MAX, index=True)
    locked_until: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
        nullable=True,
    )
    created_at: datetime = Field(
        default_factory=_utc_now,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
        nullable=False,
        index=True,
    )
    dispatched_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
        nullable=True,
    )
    dead_lettered_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
        nullable=True,
    )
    last_error: str | None = Field(default=None, max_length=_ERROR_MAX)

    def assert_within_column_bounds(self) -> None:
        """Reject a caller-influenced string that exceeds its ``VARCHAR(n)`` column bound.

        SQLite does **not** enforce ``VARCHAR`` length, but PostgreSQL does — so an
        over-length value the SQLite-backed tests silently accept would fail the INSERT
        on PostgreSQL and, because the outbox row rides the business write's own
        transaction (see :mod:`terp.capabilities.outbox.store`), fail that business
        write. Validate up front so the behaviour is identical on every backend: a clear,
        early :class:`ValueError` rather than a vendor-specific mid-transaction failure.
        """
        for column, value, limit in (
            ("name", self.name, _NAME_MAX),
            ("idempotency_key", self.idempotency_key, _KEY_MAX),
        ):
            if value is not None and len(value) > limit:
                raise ValueError(
                    f"outbox message {column!r} is {len(value)} characters, exceeding "
                    f"its {limit}-character column bound (a PostgreSQL INSERT would "
                    f"reject it and fail the business write the row rides)"
                )


__all__ = [
    "KIND_EVENT",
    "KIND_JOB",
    "STATUS_DEAD_LETTERED",
    "STATUS_DISPATCHED",
    "STATUS_PENDING",
    "OutboxMessage",
]
