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
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlmodel import Session, col

from terp.core import (
    Lease,
    LeaseGuard,
    LeaseResource,
    active_lease_store,
    hold_lease,
    register_lease_reaper,
)

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
) -> LeaseGuard | None:
    """Take the source's lease, or ``None`` when this app wired no lease store.

    Raises :class:`~terp.core.LeaseHeldError` (409) when another worker is already
    reconciling this source — the caller lets that propagate, so the queued job retries on
    its next tick rather than opening a competing run. ``None`` is the unleased path: an app
    with no store behaves exactly as it did before leasing existed.
    """
    if active_lease_store() is None:
        return None
    return hold_lease(
        session,
        sync_source_resource(tenant_scope=tenant_scope, entity_type=entity_type),
        holder=holder,
        ttl_seconds=SYNC_LEASE_TTL_SECONDS,
    )


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
    "close_stale_runs",
    "hold_source",
    "register_stale_run_reaper",
    "sync_source_resource",
    "worker_holder",
]
