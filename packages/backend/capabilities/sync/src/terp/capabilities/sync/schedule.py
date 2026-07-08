"""Schedule helpers: build a typed :class:`~terp.core.ScheduleDefinition` for a sync job.

An app puts these in its :class:`~terp.core.ScheduleCatalog` to run a reconcile on a cron. Each
tick re-evaluates the ``payload_factory`` (so the entity type travels as a fresh, serializable
payload, not a frozen closure) and enqueues ``SYNC_PULL`` / ``SYNC_PUSH`` through the typed
:func:`~terp.core.enqueue` chokepoint — flowing through the active job queue (in-process /
outbox / broker) and the context-binding runner, so a scheduled reconcile runs as the system
actor with its writes audited + stamped. The cron string is opaque here; the scheduler adapter
parses it (ADR 0048).
"""

from __future__ import annotations

import uuid

from terp.core import ScheduleDefinition

from terp.capabilities.sync.jobs import SYNC_PULL, SYNC_PUSH, SyncJobPayload


def sync_pull_schedule(
    entity_type: str, *, name: str, cron: str, tenant_id: uuid.UUID | None = None
) -> ScheduleDefinition:
    """A schedule that enqueues ``SYNC_PULL`` for *entity_type* on *cron*."""
    return ScheduleDefinition(
        name=name,
        job=SYNC_PULL,
        cron=cron,
        payload_factory=lambda: SyncJobPayload(entity_type=entity_type, tenant_id=tenant_id),
    )


def sync_push_schedule(
    entity_type: str, *, name: str, cron: str, tenant_id: uuid.UUID | None = None
) -> ScheduleDefinition:
    """A schedule that enqueues ``SYNC_PUSH`` for *entity_type* on *cron*."""
    return ScheduleDefinition(
        name=name,
        job=SYNC_PUSH,
        cron=cron,
        payload_factory=lambda: SyncJobPayload(entity_type=entity_type, tenant_id=tenant_id),
    )


__all__ = ["sync_pull_schedule", "sync_push_schedule"]
