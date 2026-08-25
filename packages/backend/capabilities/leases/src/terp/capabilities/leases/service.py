"""Operator reads over the lease table, and the "reap now" action behind the router.

The reads exist because a lease is only useful if somebody can *see* it. "The work is
still coming" and "the worker died forty minutes ago" are the same row until you know who
holds it and until when — so the router's window onto this table is part of the primitive,
not a nicety bolted on afterwards.

There is no write path here beyond reaping. Force-releasing a lease is deliberately absent:
the holder may be alive, and stealing a live lease is precisely the split-brain the fence
exists to prevent. The one sanctioned operator action is :func:`reap_now`, which recovers
only leases that have **already** lapsed — so it cannot take anything away from a worker
that is still reporting, and running it twice is a no-op.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import Session, col, func, select

from terp.core import (
    Lease,
    LeaseError,
    LeaseResource,
    LeaseStore,
    PaginationParams,
    active_lease_store,
)

from terp.capabilities.leases.models import ResourceLease
from terp.capabilities.leases.reaper import ReapResult, reap_expired_leases


def list_leases(
    session: Session,
    *,
    pagination: PaginationParams,
    kind: str | None = None,
    expired_only: bool = False,
) -> tuple[list[ResourceLease], int, datetime]:
    """One page of lease records, most-recently-touched first, plus the clock used.

    *expired_only* is the triage view — held leases whose expiry has passed, i.e. exactly
    what the next reap cycle will act on. The clock is returned alongside the rows so the
    ``expired`` flag on every row in a page is decided against **one** instant rather than
    per row.
    """
    now = _clock()
    conditions = []
    if kind is not None:
        conditions.append(col(ResourceLease.resource_kind) == kind)
    if expired_only:
        conditions.append(col(ResourceLease.holder).is_not(None))
        conditions.append(col(ResourceLease.expires_at) <= now)
    total = session.exec(
        select(func.count()).select_from(ResourceLease).where(*conditions)
    ).one()
    rows = session.exec(
        select(ResourceLease)
        .where(*conditions)
        .order_by(col(ResourceLease.touched_at).desc(), col(ResourceLease.id).desc())
        .offset(pagination.skip)
        .limit(pagination.limit)
    ).all()
    return list(rows), int(total), now


def reap_now(
    session: Session,
    *,
    kind: str | None = None,
    limit: int = 100,
) -> ReapResult:
    """Run one reap cycle on demand, against the app's configured store.

    The operator-triggered equivalent of the ``leases.reap`` job's tick — same bounded
    scan, same fenced forfeits, same registered recoveries. It deliberately does not purge:
    trimming old records is a maintenance cadence, not something to fold into an operator
    pressing a button during an incident.
    """
    return reap_expired_leases(session, _require_store(), kind=kind, limit=limit)


def heartbeat(
    session: Session,
    resource: LeaseResource,
    *,
    holder: str,
    epoch: int,
    ttl_seconds: float,
) -> Lease | None:
    """Extend *holder*'s claim on *resource*, or ``None`` if that claim is no longer theirs.

    The half of custody a holder outside this process could not reach. ``renew_lease``
    takes the granted :class:`~terp.core.Lease` value, which a worker that claims in one
    request and reports in another never has — so a foreign holder had custody and no way
    to prove liveness, and its lease degraded to a plain deadline: most of what the
    hand-rolled staleness timeout it replaced already was.

    Fenced twice over, and neither check is redundant. The read is narrowed to *holder*, so
    a caller cannot heartbeat somebody else's claim; the renew is fenced on ``epoch``, so a
    holder whose claim was already reaped and re-granted extends nothing — a late heartbeat
    from a process that had been declared dead must not take the resource back from its
    successor. ``renew`` additionally refuses an already-expired lease rather than
    resurrecting it, which is the same rule stated on the store.

    ``None`` therefore means one thing to the caller and it is the useful thing: *stop, you
    are not the holder any more*. Distinguishing "never held it" from "lost it" would tell
    the caller nothing it should act on differently.
    """
    store = _require_store()
    held = store.lease_for(session, resource, holder=holder)
    if held is None or held.epoch != epoch:
        return None
    return store.renew(session, held, ttl_seconds=ttl_seconds)


def _require_store() -> LeaseStore:
    """The app's lease store, or a :class:`~terp.core.LeaseError` naming the missing wiring."""
    store = active_lease_store()
    if store is None:
        raise LeaseError(
            "this app mounted the leases module but configured no lease store; pass "
            "create_app(lease_store=DatabaseLeaseStore()) so leases are actually taken "
            "and can be reaped"
        )
    return store


def _clock() -> datetime:
    """The store's clock when one is configured, else UTC now (reads work either way).

    A read must not fail just because no store is wired: an operator looking at an app
    mid-migration should still see the table. Only :func:`reap_now` needs a real store.
    """
    store = active_lease_store()
    return store.clock() if store is not None else datetime.now(UTC)


__all__ = ["list_leases", "reap_now"]
