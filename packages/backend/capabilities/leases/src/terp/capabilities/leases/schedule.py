"""Schedule helper: put the reap cycle on a cron through the scheduler seam.

An app declares one of these in its :class:`~terp.core.ScheduleCatalog` and the reaper
becomes operational rather than optional. Each tick re-evaluates the payload factory (so
the batch bounds travel as a fresh, serializable payload rather than a frozen closure) and
enqueues ``LEASE_REAP`` through the typed :func:`~terp.core.enqueue` chokepoint — so the
cycle flows through whatever job queue the app wired and runs as the system actor with its
recoveries audited. The cron string is opaque here; the scheduler adapter parses it
(ADR 0048).

Cadence rule of thumb: reap several times per shortest TTL. A lease that expires after 60
seconds but is only scanned hourly leaves an operator staring at a ``claimed`` row for up
to an hour — technically recoverable, indistinguishable from broken.
"""

from __future__ import annotations

from terp.core import ScheduleDefinition

from terp.capabilities.leases.jobs import LEASE_REAP, LeaseReapPayload


def lease_reap_schedule(
    *,
    name: str = "leases.reap",
    cron: str,
    kind: str | None = None,
    limit: int = 100,
    purge_idle_seconds: float | None = None,
) -> ScheduleDefinition:
    """A schedule that enqueues ``LEASE_REAP`` on *cron*.

    *kind* narrows the cycle to one resource family — declare several of these when two
    domains want different cadences — and *purge_idle_seconds*, on the cycle that carries
    it, also trims free lease records idle for that long.
    """
    return ScheduleDefinition(
        name=name,
        job=LEASE_REAP,
        cron=cron,
        payload_factory=lambda: LeaseReapPayload(
            kind=kind, limit=limit, purge_idle_seconds=purge_idle_seconds
        ),
    )


__all__ = ["lease_reap_schedule"]
