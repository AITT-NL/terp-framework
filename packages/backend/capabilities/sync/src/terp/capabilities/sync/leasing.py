"""One reconcile at a time per source, and a stale ``running`` run that reaps itself.

This capability's own docstring used to end with an admission: *"a job that dies mid-loop
leaves a ``running`` run whose work already committed per-record; the next successful run
supersedes its cursor — reaping stale runs is a follow-up."* Both halves of that sentence
were the same missing primitive (ADR 0095), read from two sides:

* **Nothing stopped two reconciles of one source overlapping.** At-least-once plus
  idempotent mappings makes that *safe*, but it is still two connections to the same
  external system computing the same answer, and the two run rows disagree about what
  happened.
* **Nothing put a dead run back.** A worker killed mid-loop left ``running`` forever. A
  reader could not tell it from a reconcile still in progress, and the only cleanup was a
  hand-written ``UPDATE``.

A lease on the *source* closes both. It is keyed on ``(tenant_scope, entity_type)`` rather
than on the run row, because what must not overlap is the **source**, not a particular
attempt — and a lease on a row that does not exist yet cannot serialise the decision to
create it. The registered reaper then closes whatever run that source left ``running``,
through the audited run service, so recovery lands in the audit trail like any other write.

Leasing stays **optional**, and that is deliberate rather than a hedge: an app that wired
no lease store reconciles exactly as it did before this module existed, so adopting the
capability is a decision about operational guarantees and never a migration. Where a store
*is* wired, ``require_durable_leases`` is what turns the guarantee on for real.

An atomic job needs a source mutex visible before its business transaction commits.
On non-SQLite engines acquisition and heartbeats therefore use an independent guarded
session. The final custody check renews on the business session itself: its row lock
fences the commit against a successor. Release happens only after commit or rollback.
The engine must supply distinct physical connections for these concurrent sessions.

SQLite cannot write a separate heartbeat while the job holds its database-wide write
lock. Its custody operations remain on the business session, with release deferred until
the transaction ends. A long SQLite write transaction serializes custody too; TTL expiry
does not let another worker take over until that transaction releases its lock. A job's
uncommitted run is not visible to the reaper and disappears on rollback. External effects
still require source-side idempotency; a database fence cannot retract a remote push.
"""

from __future__ import annotations

import uuid
from contextlib import AbstractContextManager, nullcontext
from datetime import UTC, datetime

from sqlmodel import Session, col

from terp.core import (
    Lease,
    LeaseGuard,
    LeaseLostError,
    LeaseResource,
    active_lease_store,
    hold_lease,
    register_lease_reaper,
)

from terp.core._internal.job_runtime import defer_after_job_transaction  # arch-allow-no-internal-imports: source custody must remain held until the atomic job transaction finishes, then release even after rollback
from terp.core._internal.session_guard import WriteGuardedSession, allow_session_writes, fresh_write_scope  # arch-allow-no-internal-imports: source custody uses a fresh guarded write scope; its narrow connection inspection must prove isolation before any independent commit

from terp.capabilities.sync.models import STATUS_FAILED, STATUS_RUNNING, SyncRun
from terp.capabilities.sync.schemas import SyncRunUpdate

#: The lease kind for "a reconcile of this source, in this tenant scope". Named for the
#: resource rather than the run row: two attempts at one source must not overlap, and the
#: second attempt has no row to lease until the first has let go.
SYNC_SOURCE_LEASE = "sync_source"

#: How long a reconcile may go without a heartbeat before it is considered dead. Long
#: enough that a slow external page does not lose the lease mid-loop, short enough that an
#: operator is not left staring at a ``running`` run for minutes after a worker died.
SYNC_LEASE_TTL_SECONDS = 120.0

#: The recovery message a reaped run carries, so the reason is on the row rather than only
#: in a log an operator may not have.
STALE_RUN_ERROR = (
    "the worker holding this reconcile stopped reporting; its lease expired and the run "
    "was closed so the source could be retried"
)


def sync_source_resource(*, tenant_scope: str, entity_type: str) -> LeaseResource:
    """The lease resource serialising reconciles of *entity_type* within *tenant_scope*."""
    return LeaseResource(kind=SYNC_SOURCE_LEASE, key=f"{tenant_scope}:{entity_type}")


def hold_source(
    session: Session, *, tenant_scope: str, entity_type: str, holder: str
) -> SourceLeaseGuard | None:
    """Take the source's lease, or ``None`` when this app wired no lease store.

    Raises :class:`~terp.core.LeaseHeldError` (409) when another worker is already
    reconciling this source — the caller lets that propagate, so the queued job retries on
    its next tick rather than opening a competing run. ``None`` is the unleased path: an app
    with no store behaves exactly as it did before leasing existed.
    """
    if active_lease_store() is None:
        return None
    return SourceLeaseGuard(
        session, sync_source_resource(tenant_scope=tenant_scope, entity_type=entity_type),
        holder=holder,
    )


class SourceLeaseGuard:
    """Source custody with an independent heartbeat and a transaction-fenced finish."""

    def __init__(self, session: Session, resource: LeaseResource, *, holder: str) -> None:
        self._business = session
        self._guard: LeaseGuard | None = None
        self._deferred = defer_after_job_transaction(session, self._finish)
        engine = session.get_bind().engine  # arch-allow-no-raw-connection-access: source-mutex infrastructure needs the owning engine to isolate custody from uncommitted business data, never to execute business SQL directly
        self._independent = self._deferred and engine.dialect.name != "sqlite"
        self._coordination = WriteGuardedSession(engine) if self._independent else session  # arch-allow-no-raw-session-construction: only non-SQLite job custody gets an isolated guarded session; all business writes remain on the original job session
        try:
            with self._coordination_scope():
                self._guard = hold_lease(
                    self._coordination, resource, holder=holder,
                    ttl_seconds=SYNC_LEASE_TTL_SECONDS,
                )
        except BaseException:
            if self._independent:
                self._coordination.close()
            raise

    def _coordination_scope(self) -> AbstractContextManager[None]:
        if self._independent:
            # A custom pool can hand two Sessions the same physical connection.
            # Committing that connection would commit the job's business writes.
            with allow_session_writes():
                business = self._business.connection().connection.driver_connection  # arch-allow-no-raw-connection-access: compare physical connection identities before custody DML so an unusual pool cannot commit the business transaction through its second Session
                coordination = self._coordination.connection().connection.driver_connection  # arch-allow-no-raw-connection-access: identity inspection only, to refuse a shared physical connection before an independent custody commit
            if business is coordination:
                raise RuntimeError("Sync job custody requires independent database connections")
            return fresh_write_scope()
        return nullcontext()

    def heartbeat(self) -> Lease:
        """Renew independently when due, refusing a superseded or expired holder."""
        assert self._guard is not None
        with self._coordination_scope():
            return self._guard.heartbeat()

    def check(self) -> None:
        """Fence successful local completion on the business transaction's lease lock."""
        assert self._guard is not None
        store = active_lease_store()
        assert store is not None
        renewed = store.renew(
            self._business, self._guard.lease, ttl_seconds=SYNC_LEASE_TTL_SECONDS,
        )
        if renewed is None:
            raise LeaseLostError()
        self._guard = LeaseGuard(
            self._coordination, renewed, ttl_seconds=SYNC_LEASE_TTL_SECONDS,
        )

    def release(self) -> None:
        """A job releases after its transaction; a direct service call releases now."""
        if not self._deferred:
            assert self._guard is not None
            self._guard.release()

    def _finish(self) -> None:
        try:
            if self._guard is not None:
                # The job's commit/rollback has finished. On SQLite this also
                # repairs a first-acquire SAVEPOINT committed by legacy drivers,
                # whose in-handler release would otherwise roll back on failure.
                with fresh_write_scope():
                    self._guard.release()
        finally:
            if self._independent:
                self._coordination.close()


def worker_holder() -> str:
    """An opaque holder id for one reconcile attempt.

    A fresh uuid per attempt: the holder only has to be unique, since it is the
    ``(holder, epoch)`` pair — not the name — that fences a write.
    """
    return str(uuid.uuid4())


def register_stale_run_reaper() -> None:
    """Register the recovery for an expired source lease: close its abandoned run.

    Called at import (like a scope predicate), so an app that mounts this capability gets
    the recovery whether or not it remembered to wire one.
    """
    register_lease_reaper(SYNC_SOURCE_LEASE, close_stale_runs)


def close_stale_runs(session: Session, lease: Lease) -> None:
    """Close every ``running`` run for the source whose lease lapsed (the reaper body).

    Idempotent by construction, which reaping requires: a run already closed is no longer
    ``running``, so a second cycle over the same lease finds nothing to do. The write goes
    through the audited run service, so a reaped run is as traceable as a reconciled one.
    """
    # Imported here, not at module scope: the service imports this module, so the edge has
    # to be one-way at import time.
    from terp.capabilities.sync.service import runs_service

    tenant_scope, _, entity_type = lease.resource.key.partition(":")
    service = runs_service()
    stale = session.exec(
        service.base_query().where(
            col(SyncRun.tenant_scope) == tenant_scope,
            col(SyncRun.source) == entity_type,
            col(SyncRun.status) == STATUS_RUNNING,
        )
    ).all()
    for run in stale:
        service.update(
            session,
            run.id,
            SyncRunUpdate(
                status=STATUS_FAILED,
                finished_at=datetime.now(UTC),
                error=STALE_RUN_ERROR,
                version=run.version,
            ),
        )


__all__ = [
    "STALE_RUN_ERROR",
    "SYNC_LEASE_TTL_SECONDS",
    "SYNC_SOURCE_LEASE",
    "SourceLeaseGuard",
    "close_stale_runs",
    "hold_source",
    "register_stale_run_reaper",
    "sync_source_resource",
    "worker_holder",
]
