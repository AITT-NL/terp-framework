"""Operator reads over the sync tables: runs, their record logs, and the mapping ledger.

Separate from :mod:`terp.capabilities.sync.service` because they answer a different
question with different rules. The service *writes* — every mutation through the audited
``BaseService`` chokepoint, under the source's lease. These only *read*, on behalf of an
operator looking at what a reconcile did, and they take an optional ``tenant_id`` to narrow
a view rather than to enforce isolation (the router's ``ADMIN`` policy is what gates access
to them at all).

They compose the services' ``base_query()`` where the model has row scope, so a read here
cannot drop a scope predicate the service applies.
"""

from __future__ import annotations

import uuid

from sqlmodel import Session, col, func, select

from terp.core import NotFoundError, PaginationParams

from terp.capabilities.sync.models import (
    SyncMapping,
    SyncRecordLog,
    SyncRun,
    tenant_scope_for,
)
from terp.capabilities.sync.service import SyncService, runs_service


def get_run(
    session: Session, run_id: uuid.UUID, *, tenant_id: uuid.UUID | None = None
) -> SyncRun:
    """One reconcile run by id (404 if unknown) — the router detail read."""
    query = runs_service().base_query().where(col(SyncRun.id) == run_id)
    for condition in _tenant_conditions(SyncRun, tenant_id):
        query = query.where(condition)
    run = session.exec(query).first()
    if run is None:
        raise NotFoundError()
    return run


def list_runs(
    session: Session,
    *,
    pagination: PaginationParams,
    tenant_id: uuid.UUID | None = None,
) -> tuple[list[SyncRun], int]:
    """One page of reconcile runs, newest first."""
    conditions = _tenant_conditions(SyncRun, tenant_id)
    total = session.exec(select(func.count()).select_from(SyncRun).where(*conditions)).one()
    rows = session.exec(
        select(SyncRun)
        .where(*conditions)
        .order_by(col(SyncRun.started_at).desc(), col(SyncRun.id).desc())
        .offset(pagination.skip)
        .limit(pagination.limit)
    ).all()
    return list(rows), int(total)


def list_record_logs(
    session: Session,
    *,
    pagination: PaginationParams,
    run_id: uuid.UUID,
    tenant_id: uuid.UUID | None = None,
) -> tuple[list[SyncRecordLog], int]:
    """One page of a run's append-only record log, newest first."""
    conditions = (col(SyncRecordLog.run_id) == run_id, *_tenant_conditions(SyncRecordLog, tenant_id))
    total = session.exec(
        select(func.count()).select_from(SyncRecordLog).where(*conditions)
    ).one()
    rows = session.exec(
        select(SyncRecordLog)
        .where(*conditions)
        .order_by(col(SyncRecordLog.created_at).desc(), col(SyncRecordLog.id).desc())
        .offset(pagination.skip)
        .limit(pagination.limit)
    ).all()
    return list(rows), int(total)


def list_mappings(
    session: Session,
    *,
    pagination: PaginationParams,
    entity_type: str | None = None,
    tenant_id: uuid.UUID | None = None,
) -> tuple[list[SyncMapping], int]:
    """One page of identity mappings, optionally filtered to one *entity_type*."""
    query = SyncService().base_query()
    for condition in _tenant_conditions(SyncMapping, tenant_id):
        query = query.where(condition)
    if entity_type is not None:
        query = query.where(col(SyncMapping.entity_type) == entity_type)
    total = session.exec(select(func.count()).select_from(query.subquery())).one()
    rows = session.exec(
        query.order_by(col(SyncMapping.created_at).desc())
        .offset(pagination.skip)
        .limit(pagination.limit)
    ).all()
    return list(rows), int(total)


def _tenant_conditions(model: type, tenant_id: uuid.UUID | None) -> tuple:
    """Optional tenant filter for operator reads; no filter means all sync scopes."""
    if tenant_id is None:
        return ()
    return (col(model.tenant_scope) == tenant_scope_for(tenant_id),)

__all__ = [
    "get_run",
    "list_mappings",
    "list_record_logs",
    "list_runs",
]
