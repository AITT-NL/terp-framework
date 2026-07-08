"""The sync jobs: ``SYNC_PULL`` (reconcile in ← System B) and ``SYNC_PUSH`` (push out → System B).

Both are typed :class:`~terp.core.JobDefinition` catalog constants the ``sync`` module declares
(``ModuleSpec.jobs``), so mounting the module registers them — an app then triggers them on the
scheduler seam or by hand (``terp jobs run sync.pull ...``). The handler runs in a **worker,
post-commit**: it resolves the registered :class:`~terp.capabilities.sync.remote.SyncSource` by
``entity_type`` (a name crosses the wire, never a closure) and drives the audited reconcile. The
external System-B read lives here in the handler — never in an ``_after_write`` hook (the
dual-write hazard the design forbids).
"""

from __future__ import annotations

import uuid

from sqlmodel import Field

from terp.core import BaseSchema, JobContext, JobDefinition

from terp.capabilities.sync.remote import resolve_sync_source
from terp.capabilities.sync.service import SyncService

_TYPE_MAX = 128


class SyncJobPayload(BaseSchema):
    """Which entity type to reconcile — the registered source is resolved by this name."""

    entity_type: str = Field(max_length=_TYPE_MAX)
    tenant_id: uuid.UUID | None = None


def _tenant_for_job(ctx: JobContext, payload: SyncJobPayload) -> uuid.UUID | None:
    """Tenant metadata carried by the payload, falling back to the job envelope context."""
    context_tenant = getattr(ctx, "tenant_id", None)
    if context_tenant is not None:
        return context_tenant
    tenant = payload.model_dump().get("tenant_id")
    if tenant is None:
        return None
    return tenant if isinstance(tenant, uuid.UUID) else uuid.UUID(str(tenant))


def _run_pull(ctx: JobContext, payload: SyncJobPayload) -> None:
    """Reconcile System B → local for the payload's entity type (the ``SYNC_PULL`` handler)."""
    SyncService().pull(
        ctx.session,
        resolve_sync_source(payload.entity_type),
        tenant_id=_tenant_for_job(ctx, payload),
    )


def _run_push(ctx: JobContext, payload: SyncJobPayload) -> None:
    """Push local changes → System B for the payload's entity type (the ``SYNC_PUSH`` handler)."""
    SyncService().push(
        ctx.session,
        resolve_sync_source(payload.entity_type),
        tenant_id=_tenant_for_job(ctx, payload),
    )


SYNC_PULL = JobDefinition(
    name="sync.pull", payload_schema=SyncJobPayload, handler=_run_pull
)
SYNC_PUSH = JobDefinition(
    name="sync.push", payload_schema=SyncJobPayload, handler=_run_push
)


__all__ = ["SYNC_PULL", "SYNC_PUSH", "SyncJobPayload"]
