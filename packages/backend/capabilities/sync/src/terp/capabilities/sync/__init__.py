"""terp.capabilities.sync — reconcile a local entity against an external system.

The headline *consumer* capability of the async design (§14): a maintained, secure-by-default
sync built **only** on the shipped ports — the jobs seam (:func:`terp.core.enqueue` + a typed
:class:`~terp.core.JobDefinition`), the durable outbox (retry / dead-letter), and the scheduler
seam (:class:`~terp.core.ScheduleDefinition`). It adds no engine and changes no ``terp.core``.

* An app implements one :class:`SyncSource` per entity type (``pull`` reads System B; ``apply``
  upserts the local row through an audited ``BaseService``) and registers it with
  :func:`register_sync_source` at composition time.
* It mounts the explicit :data:`module` (a *library* cap — no auto-discovery, since a sync does
  nothing without a source) and declares a schedule via :func:`sync_pull_schedule`.
* On each tick :data:`SYNC_PULL` runs in a worker: :class:`SyncService` opens a
  :class:`SyncRun`, reconciles each remote record against the :class:`SyncMapping` ledger
  (create / update / unchanged — **at-least-once + idempotent**), appends an immutable
  :class:`SyncRecordLog` line per record, and closes the run with its counts + cursor. The
  admin-only router exposes runs, logs, and mappings read-only.

It depends only on ``terp-core`` — never a sibling capability or a broker engine; the app
composes the durable ``OutboxJobQueue`` (and any broker/scheduler adapter) at ``create_app``.
"""

from __future__ import annotations

from terp.capabilities.sync.jobs import SYNC_PULL, SYNC_PUSH, SyncJobPayload
from terp.capabilities.sync.models import (
    ACTION_CREATED,
    ACTION_FAILED,
    ACTION_UNCHANGED,
    ACTION_UPDATED,
    STATUS_FAILED,
    STATUS_RUNNING,
    STATUS_SUCCEEDED,
    STATUS_SYNCED,
    SyncMapping,
    SyncRecordLog,
    SyncRun,
)
from terp.capabilities.sync.remote import (
    RemotePage,
    RemoteRecord,
    SyncError,
    SyncSource,
    register_sync_source,
    registered_sync_sources,
    reset_sync_sources,
    resolve_sync_source,
)
from terp.capabilities.sync.router import module, router
from terp.capabilities.sync.schedule import sync_pull_schedule, sync_push_schedule
from terp.capabilities.sync.schemas import (
  SyncMappingDraft,
    SyncMappingRead,
    SyncMappingUpdate,
    SyncRecordLogRead,
  SyncRunDraft,
    SyncRunRead,
    SyncRunUpdate,
)
from terp.capabilities.sync.service import (
    SyncService,
    get_run,
    list_mappings,
    list_record_logs,
    list_runs,
)
from terp.capabilities.sync.store import record_sync_log

__all__ = [
    "ACTION_CREATED",
    "ACTION_FAILED",
    "ACTION_UNCHANGED",
    "ACTION_UPDATED",
    "STATUS_FAILED",
    "STATUS_RUNNING",
    "STATUS_SUCCEEDED",
    "STATUS_SYNCED",
    "SYNC_PULL",
    "SYNC_PUSH",
    "RemotePage",
    "RemoteRecord",
    "SyncError",
    "SyncJobPayload",
    "SyncMapping",
    "SyncMappingDraft",
    "SyncMappingRead",
    "SyncMappingUpdate",
    "SyncRecordLog",
    "SyncRecordLogRead",
    "SyncRun",
    "SyncRunDraft",
    "SyncRunRead",
    "SyncRunUpdate",
    "SyncService",
    "SyncSource",
    "get_run",
    "list_mappings",
    "list_record_logs",
    "list_runs",
    "module",
    "record_sync_log",
    "register_sync_source",
    "registered_sync_sources",
    "reset_sync_sources",
    "resolve_sync_source",
    "router",
    "sync_pull_schedule",
    "sync_push_schedule",
]
