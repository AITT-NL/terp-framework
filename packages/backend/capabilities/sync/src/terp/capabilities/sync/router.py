"""Read-only admin router for sync: reconcile runs, their record logs, and the mapping ledger.

Sync is driven by jobs (``SYNC_PULL`` / ``SYNC_PUSH``), not by clients, so this router exposes
**reads only** — an operator's window into what the reconcile did (runs + counts), why
(per-record logs), and the current identity ledger (mappings). All three are privileged
operational data, so the policy requires ``ADMIN``.

Unlike a self-registering capability, ``sync`` declares **no** ``terp.capabilities``
entry point: a sync does nothing until an app registers a :class:`SyncSource`, so the app mounts
this ``module`` explicitly (``create_app(specs=[..., sync.module])``). Mounting it registers the
``SYNC_PULL`` / ``SYNC_PUSH`` jobs (``ModuleSpec.jobs``).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from terp.core import ADMIN, ModuleSpec, Page, PaginationDep, Policy, SessionDep

from terp.capabilities.sync.jobs import SYNC_PULL, SYNC_PUSH
from terp.capabilities.sync.schemas import (
    SyncMappingRead,
    SyncRecordLogRead,
    SyncRunRead,
)
from terp.capabilities.sync.service import (
    get_run,
    list_mappings,
    list_record_logs,
    list_runs,
)

router = APIRouter(tags=["sync"])


@router.get("/runs", response_model=Page[SyncRunRead])
def list_sync_runs(
    session: SessionDep,
    pagination: PaginationDep,
    tenant_id: uuid.UUID | None = None,
) -> Page[SyncRunRead]:
    rows, total = list_runs(session, pagination=pagination, tenant_id=tenant_id)
    return Page[SyncRunRead].of(
        [SyncRunRead.model_validate(row) for row in rows], total, pagination
    )


@router.get("/runs/{run_id}", response_model=SyncRunRead)
def get_sync_run(
    run_id: uuid.UUID, session: SessionDep, tenant_id: uuid.UUID | None = None
) -> SyncRunRead:
    return SyncRunRead.model_validate(get_run(session, run_id, tenant_id=tenant_id))


@router.get("/runs/{run_id}/logs", response_model=Page[SyncRecordLogRead])
def list_sync_run_logs(
    run_id: uuid.UUID,
    session: SessionDep,
    pagination: PaginationDep,
    tenant_id: uuid.UUID | None = None,
) -> Page[SyncRecordLogRead]:
    rows, total = list_record_logs(
        session, pagination=pagination, run_id=run_id, tenant_id=tenant_id
    )
    return Page[SyncRecordLogRead].of(
        [SyncRecordLogRead.model_validate(row) for row in rows], total, pagination
    )


@router.get("/mappings", response_model=Page[SyncMappingRead])
def list_sync_mappings(
    session: SessionDep,
    pagination: PaginationDep,
    entity_type: str | None = None,
    tenant_id: uuid.UUID | None = None,
) -> Page[SyncMappingRead]:
    rows, total = list_mappings(
        session, pagination=pagination, entity_type=entity_type, tenant_id=tenant_id
    )
    return Page[SyncMappingRead].of(
        [SyncMappingRead.model_validate(row) for row in rows], total, pagination
    )


module = ModuleSpec(
    name="sync",
    router=router,
    jobs=(SYNC_PULL, SYNC_PUSH),
    policy=Policy(read=ADMIN, write=ADMIN),
)


__all__ = ["module", "router"]
