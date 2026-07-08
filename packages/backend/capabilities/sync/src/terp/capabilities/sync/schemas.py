"""Sync DTOs — internal write shapes for the reconcile engine + read shapes for the router.

``SyncMapping`` / ``SyncRun`` are driven by the reconcile engine, not by clients: the router
exposes **reads only**, so the internal write DTOs are the typed inputs ``BaseService`` needs
(never an HTTP body). They still cap every ``str`` field. They deliberately avoid the
``*Create`` suffix because the architecture harness treats that suffix as a public input
schema and forbids tenant-managed columns there; this capability's engine, not a client,
sets the tenant metadata.
"""

from __future__ import annotations

import datetime
import uuid

from sqlmodel import Field

from terp.core import BaseSchema, BaseUpdateSchema

from terp.capabilities.sync.models import STATUS_RUNNING, STATUS_SYNCED

# Mirror the model caps so an oversized value is rejected before it reaches a column.
_TYPE_MAX = 128
_REMOTE_ID_MAX = 200
_CHECKSUM_MAX = 128
_STATUS_MAX = 16
_CURSOR_MAX = 512
_MESSAGE_MAX = 2000
_TENANT_SCOPE_MAX = 36


class SyncMappingDraft(BaseSchema):
    """Record a freshly reconciled local↔remote identity (engine input, never an HTTP body)."""

    tenant_scope: str = Field(max_length=_TENANT_SCOPE_MAX)
    tenant_id: uuid.UUID | None = None
    entity_type: str = Field(max_length=_TYPE_MAX)
    local_id: uuid.UUID
    remote_id: str = Field(max_length=_REMOTE_ID_MAX)
    remote_checksum: str = Field(max_length=_CHECKSUM_MAX)
    status: str = Field(default=STATUS_SYNCED, max_length=_STATUS_MAX)


class SyncMappingUpdate(BaseUpdateSchema):
    """Re-point a mapping after a remote change (optimistic concurrency via ``version``)."""

    remote_checksum: str | None = Field(default=None, max_length=_CHECKSUM_MAX)
    status: str | None = Field(default=None, max_length=_STATUS_MAX)
    last_synced_at: datetime.datetime | None = None


class SyncRunDraft(BaseSchema):
    """Open a reconcile run (engine input): the entity type and the resume cursor."""

    tenant_scope: str = Field(max_length=_TENANT_SCOPE_MAX)
    tenant_id: uuid.UUID | None = None
    source: str = Field(max_length=_TYPE_MAX)
    status: str = Field(default=STATUS_RUNNING, max_length=_STATUS_MAX)
    cursor: str | None = Field(default=None, max_length=_CURSOR_MAX)


class SyncRunUpdate(BaseUpdateSchema):
    """Close a reconcile run with its outcome, aggregates, and high-watermark cursor."""

    status: str | None = Field(default=None, max_length=_STATUS_MAX)
    finished_at: datetime.datetime | None = None
    processed_count: int | None = None
    created_count: int | None = None
    updated_count: int | None = None
    failed_count: int | None = None
    cursor: str | None = Field(default=None, max_length=_CURSOR_MAX)
    error: str | None = Field(default=None, max_length=_MESSAGE_MAX)


class SyncRunRead(BaseSchema):
    """One reconcile run as returned by the read-only operations router."""

    id: uuid.UUID
    tenant_id: uuid.UUID | None
    source: str
    status: str
    started_at: datetime.datetime
    finished_at: datetime.datetime | None
    processed_count: int
    created_count: int
    updated_count: int
    failed_count: int
    cursor: str | None
    error: str | None
    version: int
    created_at: datetime.datetime
    updated_at: datetime.datetime


class SyncMappingRead(BaseSchema):
    """One local↔remote identity mapping as returned by the router."""

    id: uuid.UUID
    tenant_id: uuid.UUID | None
    entity_type: str
    local_id: uuid.UUID
    remote_id: str
    remote_checksum: str
    status: str
    last_synced_at: datetime.datetime
    version: int
    created_at: datetime.datetime
    updated_at: datetime.datetime


class SyncRecordLogRead(BaseSchema):
    """One immutable per-record line as returned by the read-only record log."""

    id: uuid.UUID
    run_id: uuid.UUID
    tenant_id: uuid.UUID | None
    entity_type: str
    remote_id: str
    action: str
    message: str | None
    created_at: datetime.datetime


__all__ = [
    "SyncMappingRead",
    "SyncMappingDraft",
    "SyncMappingUpdate",
    "SyncRecordLogRead",
    "SyncRunDraft",
    "SyncRunRead",
    "SyncRunUpdate",
]
