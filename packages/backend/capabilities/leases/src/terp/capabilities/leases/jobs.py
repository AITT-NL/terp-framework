"""``LEASE_REAP`` — reaping as a declared job, so it runs wherever background work runs.

A reaper that only exists as a CLI command is a reaper somebody has to remember to
schedule, and "nothing reaped the stale claim" looks exactly like "the work is still
coming". So the cycle is a typed :class:`~terp.core.JobDefinition` the ``leases`` module
declares: mounting the module registers it, and it then runs through whatever an app
already operates — the APScheduler process, Celery beat, a Kubernetes ``CronJob`` calling
``terp jobs run leases.reap``, or ``terp leases reap`` directly. There is no new daemon to
deploy, which is the whole reason it is a job and not a thread.

The handler runs in a worker, post-commit, through the context-binding runner — so the
domain recoveries it triggers are audited and actor-stamped exactly like any other write.
It is safe to run concurrently with itself: the scan is bounded and every forfeit is
fenced, so two reapers overlapping recover disjoint sets rather than the same lease twice.
"""

from __future__ import annotations

from sqlmodel import Field

from terp.core import (
    LEASE_KIND_MAX,
    BaseSchema,
    JobContext,
    JobDefinition,
    LeaseError,
    RetryPolicy,
    active_lease_store,
)

from terp.capabilities.leases.reaper import reap_expired_leases

# A reap cycle is cheap and runs again on the next tick, so a long retry ladder would only
# pile duplicate cycles behind a transient database blip. Two attempts, then wait for the
# schedule.
_REAP_RETRY = RetryPolicy(max_attempts=2)


class LeaseReapPayload(BaseSchema):
    """Which lapsed leases to recover this cycle, and how much to do at once."""

    kind: str | None = Field(default=None, max_length=LEASE_KIND_MAX)
    limit: int = Field(default=100, ge=1, le=1000)
    purge_idle_seconds: float | None = Field(default=None, gt=0)


def _run_reap(ctx: JobContext, payload: LeaseReapPayload) -> None:
    """Recover one bounded batch of lapsed leases (the ``LEASE_REAP`` handler)."""
    store = active_lease_store()
    if store is None:
        raise LeaseError(
            "leases.reap ran with no lease store configured; pass "
            "create_app(lease_store=DatabaseLeaseStore()) — the reaper has nothing to "
            "scan without it"
        )
    reap_expired_leases(
        ctx.session,
        store,
        kind=payload.kind,
        limit=payload.limit,
        purge_idle_seconds=payload.purge_idle_seconds,
    )


LEASE_REAP = JobDefinition(
    name="leases.reap",
    payload_schema=LeaseReapPayload,
    handler=_run_reap,
    retry=_REAP_RETRY,
)


__all__ = ["LEASE_REAP", "LeaseReapPayload"]
