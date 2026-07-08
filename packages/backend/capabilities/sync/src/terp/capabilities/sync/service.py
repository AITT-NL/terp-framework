"""The reconcile engine: audited run + mapping writes, plus the append-only record log.

:class:`SyncService` is a ``BaseService[SyncMapping, ...]`` — so every mapping write it makes
is stamped and audited by the kernel — and it drives the run aggregates through a second
``BaseService`` (``_SyncRunService``). The reconcile is the design's §18 shape:

* open a :class:`~terp.capabilities.sync.models.SyncRun` (``running``), resuming from the
    cursor of the last **succeeded** run for the same tenant scope;
* for each remote record, look up the mapping by ``(tenant_scope, entity_type, remote_id)``
    and either create (unseen), update (checksum changed), or skip (unchanged) the local row
    **through the source's audited** :meth:`~terp.capabilities.sync.remote.SyncSource.apply` —
    appending one record-log line per record;
* close the run ``succeeded`` with the counts and the next cursor.

The model is **at-least-once + idempotent** (design §6 rule 3): a mapping is keyed uniquely
from both sides, and a record's checksum makes a redelivery a no-op, so a retried job re-runs
safely. A per-record failure is logged (``failed``/``ACTION_FAILED``) and does not abort the
run; a failure in the *pull itself* closes the run ``failed`` and re-raises so the outbox
retries the whole job. (A job that dies mid-loop leaves a ``running`` run whose work already
committed per-record; the next successful run supersedes its cursor — reaping stale runs is a
follow-up.)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlmodel import Session, col, func, select

from terp.core import AuditAction, BaseService, NotFoundError, PaginationParams

from terp.capabilities.sync.models import (
    ACTION_CREATED,
    ACTION_FAILED,
    ACTION_UNCHANGED,
    ACTION_UPDATED,
    STATUS_FAILED,
    STATUS_SUCCEEDED,
    SyncMapping,
    SyncRecordLog,
    SyncRun,
)
from terp.capabilities.sync.remote import SyncSource
from terp.capabilities.sync.schemas import (
    SyncMappingDraft,
    SyncMappingUpdate,
    SyncRunDraft,
    SyncRunUpdate,
)
from terp.capabilities.sync.store import clip_sync_message, record_sync_log


def _utc_now() -> datetime:
    """UTC ``now`` for run timestamps."""
    return datetime.now(UTC)


@dataclass
class _Counts:
    """In-memory tally of a reconcile, folded into the run row once at close."""

    processed: int = 0
    created: int = 0
    updated: int = 0
    failed: int = 0


class _SyncRunService(BaseService[SyncRun, SyncRunDraft, SyncRunUpdate]):
    model = SyncRun

    def open(
        self,
        session: Session,
        *,
        tenant_scope: str,
        tenant_id: uuid.UUID | None,
        source: str,
        cursor: str | None = None,
    ) -> SyncRun:
        return self._save(
            session,
            SyncRun(
                tenant_scope=tenant_scope,
                tenant_id=tenant_id,
                source=source,
                cursor=cursor,
            ),
            AuditAction.CREATED,
        )


_runs = _SyncRunService()


def _tenant_scope(tenant_id: uuid.UUID | None) -> str:
    """The non-null tenant dimension used in unique keys (``global`` for single-tenant)."""
    return str(tenant_id) if tenant_id is not None else "global"


class SyncService(BaseService[SyncMapping, SyncMappingDraft, SyncMappingUpdate]):
    """Reconcile a local entity type against a registered
    :class:`~terp.capabilities.sync.remote.SyncSource`."""

    model = SyncMapping

    def pull(
        self, session: Session, source: SyncSource, *, tenant_id: uuid.UUID | None = None
    ) -> SyncRun:
        """Reconcile System B → local for *source*, returning the closed run."""
        tenant_scope = _tenant_scope(tenant_id)
        resume = self._resume_cursor(session, source.entity_type, tenant_scope)
        run = _runs.open(
            session,
            tenant_scope=tenant_scope,
            tenant_id=tenant_id,
            source=source.entity_type,
            cursor=resume,
        )
        run_id, run_version = run.id, run.version
        counts = _Counts()
        try:
            page = source.pull(resume)
            for record in page.records:
                self._reconcile_record(
                    session, source, record, run_id, tenant_scope, tenant_id, counts
                )
            _runs.update(
                session,
                run_id,
                SyncRunUpdate(
                    status=STATUS_SUCCEEDED,
                    finished_at=_utc_now(),
                    processed_count=counts.processed,
                    created_count=counts.created,
                    updated_count=counts.updated,
                    failed_count=counts.failed,
                    cursor=page.next_cursor,
                    version=run_version,
                ),
            )
        except Exception as exc:
            _runs.update(
                session,
                run_id,
                SyncRunUpdate(
                    status=STATUS_FAILED,
                    finished_at=_utc_now(),
                    processed_count=counts.processed,
                    created_count=counts.created,
                    updated_count=counts.updated,
                    failed_count=counts.failed,
                    error=clip_sync_message(str(exc)),
                    version=run_version,
                ),
            )
            raise
        return _runs.get(session, run_id)

    def push(
        self, session: Session, source: SyncSource, *, tenant_id: uuid.UUID | None = None
    ) -> SyncRun:
        """Push local changes → System B via the source, returning the closed run.

        Delegates the direction to :meth:`~terp.capabilities.sync.remote.SyncSource.push`
        (unsupported by default — a pull-only source closes the run ``failed`` and re-raises).
        """
        tenant_scope = _tenant_scope(tenant_id)
        run = _runs.open(
            session,
            tenant_scope=tenant_scope,
            tenant_id=tenant_id,
            source=source.entity_type,
        )
        run_id, run_version = run.id, run.version
        try:
            pushed = source.push(session)
            _runs.update(
                session,
                run_id,
                SyncRunUpdate(
                    status=STATUS_SUCCEEDED,
                    finished_at=_utc_now(),
                    processed_count=pushed,
                    updated_count=pushed,
                    version=run_version,
                ),
            )
        except Exception as exc:
            _runs.update(
                session,
                run_id,
                SyncRunUpdate(
                    status=STATUS_FAILED,
                    finished_at=_utc_now(),
                    error=clip_sync_message(str(exc)),
                    version=run_version,
                ),
            )
            raise
        return _runs.get(session, run_id)

    def _reconcile_record(
        self,
        session: Session,
        source: SyncSource,
        record: object,
        run_id: uuid.UUID,
        tenant_scope: str,
        tenant_id: uuid.UUID | None,
        counts: _Counts,
    ) -> None:
        """Create / update / skip one local row, appending exactly one record-log line."""
        remote_id = record.remote_id  # type: ignore[attr-defined]
        checksum = record.checksum  # type: ignore[attr-defined]
        try:
            mapping = self._mapping_for(
                session, tenant_scope, source.entity_type, remote_id
            )
            if mapping is None:
                local_id = source.apply(session, record, None)  # type: ignore[arg-type]
                self._create_mapping(
                    session,
                    tenant_scope=tenant_scope,
                    tenant_id=tenant_id,
                    entity_type=source.entity_type,
                    local_id=local_id,
                    remote_id=remote_id,
                    remote_checksum=checksum,
                )
                action = ACTION_CREATED
                counts.created += 1
            elif mapping.remote_checksum != checksum:
                source.apply(session, record, mapping.local_id)  # type: ignore[arg-type]
                self.update(
                    session,
                    mapping.id,
                    SyncMappingUpdate(
                        remote_checksum=checksum,
                        last_synced_at=_utc_now(),
                        version=mapping.version,
                    ),
                )
                action = ACTION_UPDATED
                counts.updated += 1
            else:
                action = ACTION_UNCHANGED
            record_sync_log(
                session,
                run_id=run_id,
                tenant_scope=tenant_scope,
                tenant_id=tenant_id,
                entity_type=source.entity_type,
                remote_id=remote_id,
                action=action,
            )
        except Exception as exc:  # noqa: BLE001 - a bad record is logged, not fatal to the run
            counts.failed += 1
            record_sync_log(
                session,
                run_id=run_id,
                tenant_scope=tenant_scope,
                tenant_id=tenant_id,
                entity_type=source.entity_type,
                remote_id=remote_id,
                action=ACTION_FAILED,
                message=str(exc),
            )
        counts.processed += 1

    def _mapping_for(
        self, session: Session, tenant_scope: str, entity_type: str, remote_id: str
    ) -> SyncMapping | None:
        """The mapping for ``(tenant_scope, entity_type, remote_id)`` on row scope."""
        return session.exec(
            self.base_query().where(
                col(SyncMapping.tenant_scope) == tenant_scope,
                col(SyncMapping.entity_type) == entity_type,
                col(SyncMapping.remote_id) == remote_id,
            )
        ).first()

    def _create_mapping(
        self,
        session: Session,
        *,
        tenant_scope: str,
        tenant_id: uuid.UUID | None,
        entity_type: str,
        local_id: uuid.UUID,
        remote_id: str,
        remote_checksum: str,
    ) -> SyncMapping:
        return self._save(
            session,
            SyncMapping(
                tenant_scope=tenant_scope,
                tenant_id=tenant_id,
                entity_type=entity_type,
                local_id=local_id,
                remote_id=remote_id,
                remote_checksum=remote_checksum,
            ),
            AuditAction.CREATED,
        )

    def _resume_cursor(
        self, session: Session, source: str, tenant_scope: str
    ) -> str | None:
        """The cursor of the last **succeeded** run for *source* + tenant scope."""
        last = session.exec(
            select(SyncRun)
            .where(
                col(SyncRun.tenant_scope) == tenant_scope,
                col(SyncRun.source) == source,
                col(SyncRun.status) == STATUS_SUCCEEDED,
            )
            .order_by(col(SyncRun.started_at).desc())
        ).first()
        return last.cursor if last else None


def get_run(
    session: Session, run_id: uuid.UUID, *, tenant_id: uuid.UUID | None = None
) -> SyncRun:
    """One reconcile run by id (404 if unknown) — the router detail read."""
    query = _runs.base_query().where(col(SyncRun.id) == run_id)
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
    return (col(model.tenant_scope) == _tenant_scope(tenant_id),)




__all__ = [
    "SyncService",
    "get_run",
    "list_mappings",
    "list_record_logs",
    "list_runs",
]
