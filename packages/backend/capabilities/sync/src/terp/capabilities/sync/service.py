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
retries the whole job. The job transaction rolls back local rows, mappings, record logs,
and cursor advancement. Its failed-run journal is then written independently through the
audited service, preserving the failure without committing those business changes.

A reconcile also takes a **lease on its source** for as long as it runs
(:mod:`terp.capabilities.sync.leasing`), which answers the two questions this docstring used
to leave open. Two reconciles of one source no longer overlap — the second is refused with
:class:`~terp.core.LeaseHeldError` and retries on its next tick, instead of opening a
competing run against the same external system. And a job that dies mid-loop no longer
leaves ``running`` forever: its lease lapses, the registered reaper closes the abandoned run
``failed`` with the reason on the row, and the source becomes retryable — where previously
the only cleanup was a hand-written ``UPDATE``. The lease is renewed from inside the record
loop and fails closed if it was taken over, so a worker that stalled past its expiry stops
rather than finishing over its successor. An app that wired no lease store reconciles exactly
as before (``leases`` is a capability it opts into), so nothing here is a migration.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlmodel import Session, col, select

from terp.core import AuditAction, BaseService, StaleDataError

from terp.core._internal.job_runtime import defer_after_job_transaction  # arch-allow-no-internal-imports: failed sync-attempt journals must survive job rollback without committing the job's local business writes
from terp.core._internal.session_guard import WriteGuardedSession  # arch-allow-no-internal-imports: the deferred attempt journal uses a fresh guarded session and the audited run service after the job transaction has finished

from terp.capabilities.sync.leasing import (
    SourceLeaseGuard,
    hold_source,
    register_stale_run_reaper,
    worker_holder,
)
from terp.capabilities.sync.models import (
    ACTION_CREATED,
    ACTION_FAILED,
    ACTION_UNCHANGED,
    ACTION_UPDATED,
    STATUS_FAILED,
    STATUS_RUNNING,
    STATUS_SUCCEEDED,
    SyncMapping,
    SyncRun,
    tenant_scope_for,
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

    def fail(
        self, session: Session, opened: SyncRun, outcome: SyncRunUpdate,
        *, local_effects: bool = True,
    ) -> None:
        """Journal a failed attempt after a job's business transaction finishes.

        ``opened`` is a detached snapshot taken before calling the source. A failed
        job rolls its new run back together with its business writes; only this
        narrow run journal is recreated afterward. Its counts cannot claim local
        creations or updates that were rolled back, and its resume cursor remains
        the one captured at open. Record logs and mappings are not replayed. A push
        preserves a count its external source already confirmed: database rollback
        cannot retract that external effect.

        A custom handler can catch the source failure and finish its transaction.
        Then the original run still exists and gets its ordinary audited outcome,
        unless a reaper or another writer already closed or advanced it. The same
        optimistic fence protects a concurrent change between reading and updating.
        """
        engine = session.get_bind().engine  # arch-allow-no-raw-connection-access: failed-attempt infrastructure reuses only the database engine for its post-transaction journal; it never runs business SQL through a raw connection

        def journal() -> None:
            with WriteGuardedSession(engine) as journal_session:  # arch-allow-no-raw-session-construction: the attempt journal needs an independent guarded transaction after job commit or rollback, and writes only through the audited run service
                current = self.find(journal_session, opened.id)
                if current is None:
                    values = opened.model_dump() | outcome.model_dump(
                        exclude_unset=True, exclude={"version"},
                    )
                    if local_effects:
                        values.update(created_count=0, updated_count=0)
                    self._save(journal_session, SyncRun.model_validate(values), AuditAction.CREATED)
                elif current.status == STATUS_RUNNING and current.version == outcome.version:
                    try:
                        self.update(journal_session, current.id, outcome)
                    except StaleDataError:
                        # The concurrent winner's verdict owns this run; a delayed
                        # failure report must not overwrite it.
                        pass

        if not defer_after_job_transaction(session, journal):
            self.update(session, opened.id, outcome)


_runs = _SyncRunService()


def runs_service() -> _SyncRunService:
    """The audited run service, for the stale-run reaper (which must not re-instantiate it)."""
    return _runs


# Registering at import mirrors a scope predicate: an app that mounts this capability gets
# the stale-run recovery without having to remember to wire it.
register_stale_run_reaper()


class SyncService(BaseService[SyncMapping, SyncMappingDraft, SyncMappingUpdate]):
    """Reconcile a local entity type against a registered
    :class:`~terp.capabilities.sync.remote.SyncSource`."""

    model = SyncMapping

    def pull(
        self, session: Session, source: SyncSource, *, tenant_id: uuid.UUID | None = None
    ) -> SyncRun:
        """Reconcile System B → local for *source*, returning the closed run.

        Held under the source's lease for the whole reconcile (see
        :mod:`terp.capabilities.sync.leasing`): a competing reconcile of the same source is
        refused before a run is opened, and one that dies here is reaped rather than left
        ``running``. The lease is taken **before** the run row exists, because what must not
        overlap is the source — refusing after opening a run would leave the evidence of a
        reconcile that never happened.
        """
        tenant_scope = tenant_scope_for(tenant_id)
        guard = hold_source(
            session,
            tenant_scope=tenant_scope,
            entity_type=source.entity_type,
            holder=worker_holder(),
        )
        try:
            return self._pull_leased(
                session, source, tenant_scope=tenant_scope, tenant_id=tenant_id, guard=guard
            )
        finally:
            if guard is not None:
                # Jobs defer the fenced release until their business transaction
                # finishes, so rolling back a failed attempt cannot undo the release.
                guard.release()

    def _pull_leased(
        self,
        session: Session,
        source: SyncSource,
        *,
        tenant_scope: str,
        tenant_id: uuid.UUID | None,
        guard: SourceLeaseGuard | None,
    ) -> SyncRun:
        """The reconcile itself, with the source's lease already held."""
        resume = self._resume_cursor(session, source.entity_type, tenant_scope)
        run = _runs.open(
            session,
            tenant_scope=tenant_scope,
            tenant_id=tenant_id,
            source=source.entity_type,
            cursor=resume,
        )
        run_id, run_version = run.id, run.version
        opened = SyncRun.model_validate(run.model_dump())
        counts = _Counts()
        try:
            page = source.pull(resume)
            for record in page.records:
                if guard is not None:
                    # Cheap per record (it writes only past the lease's half-life) and
                    # fail-closed: if the lease was taken over, this raises and the run is
                    # closed failed instead of racing its successor to the finish.
                    guard.heartbeat()
                self._reconcile_record(
                    session, source, record, run_id, tenant_scope, tenant_id, counts
                )
            if guard is not None:
                guard.check()
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
            _runs.fail(
                session,
                opened,
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

        ``push`` is one opaque external call. The final custody check joins the local
        business transaction, so an expired or superseded holder cannot commit its local
        outcome. That cannot retract an external write already performed by the source:
        the destination still needs its own idempotency or fencing contract. The run's
        optimistic version also preserves a reaper's verdict if it already closed the run.
        """
        tenant_scope = tenant_scope_for(tenant_id)
        # The same lease as pull, on purpose: a push and a pull of one source both write the
        # same mapping ledger, so they must not overlap either.
        guard = hold_source(
            session,
            tenant_scope=tenant_scope,
            entity_type=source.entity_type,
            holder=worker_holder(),
        )
        try:
            return self._push_leased(
                session, source, tenant_scope=tenant_scope, tenant_id=tenant_id, guard=guard
            )
        finally:
            if guard is not None:
                # Everything after the lease was taken is inside the try, so a failure while
                # *opening* the run hands the source back too — rather than leaving it locked
                # out for a whole TTL over a run that never started.
                guard.release()

    def _push_leased(
        self,
        session: Session,
        source: SyncSource,
        *,
        tenant_scope: str,
        tenant_id: uuid.UUID | None,
        guard: SourceLeaseGuard | None,
    ) -> SyncRun:
        """The push itself, with the source's lease already held."""
        run = _runs.open(
            session,
            tenant_scope=tenant_scope,
            tenant_id=tenant_id,
            source=source.entity_type,
        )
        run_id, run_version = run.id, run.version
        opened = SyncRun.model_validate(run.model_dump())
        pushed = 0
        try:
            pushed = source.push(session)
            if guard is not None:
                guard.check()
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
            _runs.fail(
                session,
                opened,
                SyncRunUpdate(
                    status=STATUS_FAILED,
                    finished_at=_utc_now(),
                    processed_count=pushed,
                    updated_count=pushed,
                    error=clip_sync_message(str(exc)),
                    version=run_version,
                ),
                local_effects=False,
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


__all__ = ["SyncService", "runs_service"]
