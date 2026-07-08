"""Sync tables: the identity ledger, per-run aggregates, and an append-only record log.

A sync reconciles a local entity type against an external system. Three tables back it:

* :class:`SyncMapping` (``BaseTable``) — the identity ledger tying a local row to its remote
    counterpart. Unique on (``tenant_scope``, ``entity_type``, ``local_id``) **and**
    (``tenant_scope``, ``entity_type``, ``remote_id``), so an upsert is idempotent from either
    side without colliding across tenants — the natural at-least-once dedupe key the design (§6
    rule 3) leans on.
* :class:`SyncRun` (``BaseTable``) — one reconcile attempt's aggregates (counts + the
  high-watermark ``cursor``), stored so a stats view never pays a per-row ``COUNT(*)``
  (review M5).
* :class:`SyncRecordLog` — one append-only line per record processed, immutable exactly like
  :class:`~terp.capabilities.audit.AuditEvent` (``UUIDPrimaryKeyMixin``, no OCC ``version`` /
  ``updated_at``); high-volume, so plan retention.

Every caller-influenceable ``str`` column caps its length.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Final

from sqlalchemy import DateTime, UniqueConstraint
from sqlmodel import Field, SQLModel

from terp.core import BaseTable, UUIDPrimaryKeyMixin

# Mapping/run status + record-log actions (plain str columns, dependency-light leaves like
# ``AuditEvent.action`` — never a higher-layer enum on the table).
STATUS_SYNCED: Final[str] = "synced"
STATUS_RUNNING: Final[str] = "running"
STATUS_SUCCEEDED: Final[str] = "succeeded"
STATUS_FAILED: Final[str] = "failed"

ACTION_CREATED: Final[str] = "created"
ACTION_UPDATED: Final[str] = "updated"
ACTION_UNCHANGED: Final[str] = "unchanged"
ACTION_FAILED: Final[str] = "failed"

# Hard caps so a hostile / oversized value can never break the INSERT or the ledger.
_TYPE_MAX: Final[int] = 128
_REMOTE_ID_MAX: Final[int] = 200
_CHECKSUM_MAX: Final[int] = 128
_STATUS_MAX: Final[int] = 16
_ACTION_MAX: Final[int] = 16
_CURSOR_MAX: Final[int] = 512
_MESSAGE_MAX: Final[int] = 2000
_GLOBAL_TENANT_SCOPE: Final[str] = "global"


def _utc_now() -> datetime:
    """UTC ``now`` provider for the timestamp columns."""
    return datetime.now(UTC)


class SyncMapping(BaseTable, table=True):
    """The identity ledger: one local row ↔ one remote row for an ``entity_type``.

    ``id`` / ``created_at`` / ``updated_at`` / ``version`` are inherited from ``BaseTable``.
    The two unique constraints make the mapping the idempotent upsert key from either side, so
    an at-least-once redelivery of the same remote record never double-creates a local row.
    ``remote_checksum`` lets the reconcile detect a change without deep-diffing the payload.
    """

    __tablename__ = "sync_mapping"
    __table_args__ = (
        UniqueConstraint(
            "tenant_scope", "entity_type", "local_id", name="uq_sync_mapping_local"
        ),
        UniqueConstraint(
            "tenant_scope", "entity_type", "remote_id", name="uq_sync_mapping_remote"
        ),
    )

    tenant_scope: str = Field(default=_GLOBAL_TENANT_SCOPE, max_length=36, index=True)
    tenant_id: uuid.UUID | None = Field(default=None, index=True)
    entity_type: str = Field(max_length=_TYPE_MAX, index=True)
    local_id: uuid.UUID = Field(index=True)
    remote_id: str = Field(max_length=_REMOTE_ID_MAX, index=True)
    remote_checksum: str = Field(max_length=_CHECKSUM_MAX)
    status: str = Field(default=STATUS_SYNCED, max_length=_STATUS_MAX, index=True)
    last_synced_at: datetime = Field(
        default_factory=_utc_now,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
        nullable=False,
    )


class SyncRun(BaseTable, table=True):
    """One reconcile attempt for a ``source`` (entity type): status, counts, and cursor.

    Aggregates are stored here (``processed_count`` / ``created_count`` / ``updated_count`` /
    ``failed_count``) so a stats view reads a single row instead of counting the log; the
    high-watermark ``cursor`` is where the next run resumes.
    """

    __tablename__ = "sync_run"

    tenant_scope: str = Field(default=_GLOBAL_TENANT_SCOPE, max_length=36, index=True)
    tenant_id: uuid.UUID | None = Field(default=None, index=True)
    source: str = Field(max_length=_TYPE_MAX, index=True)
    status: str = Field(default=STATUS_RUNNING, max_length=_STATUS_MAX, index=True)
    started_at: datetime = Field(
        default_factory=_utc_now,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
        nullable=False,
        index=True,
    )
    finished_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
        nullable=True,
    )
    processed_count: int = Field(default=0)
    created_count: int = Field(default=0)
    updated_count: int = Field(default=0)
    failed_count: int = Field(default=0)
    cursor: str | None = Field(default=None, max_length=_CURSOR_MAX)
    error: str | None = Field(default=None, max_length=_MESSAGE_MAX)


class SyncRecordLog(UUIDPrimaryKeyMixin, SQLModel, table=True):  # arch-allow-table-models-use-base-table: append-only per-record log (like AuditEvent) — immutable, no version/updated_at by design (see module docstring)
    __tablename__ = "sync_record_log"

    run_id: uuid.UUID = Field(index=True)
    tenant_scope: str = Field(default=_GLOBAL_TENANT_SCOPE, max_length=36, index=True)
    tenant_id: uuid.UUID | None = Field(default=None, index=True)
    entity_type: str = Field(max_length=_TYPE_MAX, index=True)
    remote_id: str = Field(max_length=_REMOTE_ID_MAX, index=True)
    action: str = Field(max_length=_ACTION_MAX, index=True)
    message: str | None = Field(default=None, max_length=_MESSAGE_MAX)
    created_at: datetime = Field(
        default_factory=_utc_now,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
        nullable=False,
        index=True,
    )


__all__ = [
    "ACTION_CREATED",
    "ACTION_FAILED",
    "ACTION_UNCHANGED",
    "ACTION_UPDATED",
    "STATUS_FAILED",
    "STATUS_RUNNING",
    "STATUS_SUCCEEDED",
    "STATUS_SYNCED",
    "SyncMapping",
    "SyncRecordLog",
    "SyncRun",
]
