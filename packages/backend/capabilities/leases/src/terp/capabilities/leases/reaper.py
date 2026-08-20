"""The reaper — the half of expiry that puts the *domain* back, not just the resource.

An expired lease frees a resource. It does not free the work: the row a dead worker left
``claimed``, the run it left ``running``, are still exactly as it left them, and no generic
mechanism can know whether the right recovery is "queue it again", "close it failed" or
"leave it for a human". Only the domain knows, which is why it registers a
:data:`~terp.core.LeaseReaper` for its resource kind
(:func:`~terp.core.register_lease_reaper`) and this module runs it.

One cycle: scan a bounded batch of lapsed leases, and for each one run its registered
recovery and forfeit the lease **in a single transaction**. That atomicity is the reason
:meth:`~terp.core.BaseService._save` is re-entrant — the domain's recovery write joins this
unit instead of committing on its own — and it is what keeps the cycle honest: recovery
without forfeit would re-run every cycle forever, and forfeit without recovery would lose
the only record that the work needs picking up.

Three outcomes per lease, all of them normal:

* **recovered** — a reaper was registered, it ran, the lease was forfeited.
* **released** — no reaper for this kind, so expiry *was* the whole recovery. That is the
  correct shape for a pure mutex ("at most one active run per pipeline"): there is no row
  to walk back, and the resource simply becomes available. The lease is still forfeited, or
  the scan would return it on every cycle forever.
* **failed** — the reaper raised. The lease is left held-and-expired on purpose, so the
  next cycle tries again; one domain's bad recovery never aborts the cycle for the others.

Because a lease can be recovered more than once (a crash between recovery and commit, a
reaper that failed after a partial write), a registered reaper must be **idempotent** —
at-least-once applies here exactly as it does to job delivery.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlmodel import Session

from terp.core import Lease, LeaseStore, lease_reaper_for

# The recovery write and the forfeit must land together, so the reaper opens one write unit
# and lets the domain's own audited ``_save`` nest inside it (ADR 0038's re-entrancy). The
# scope primitive is _internal so an app module cannot open it to wave a write past the
# audit guard; framework infrastructure legitimately reaches it.
from terp.core._internal.session_guard import enter_write_unit  # arch-allow-no-internal-imports: recovery + forfeit must commit as one unit, so the reaper opens the write unit the domain's audited _save nests into

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReapResult:
    """The tally of one reap cycle — what an operator and the CLI both read."""

    scanned: int = 0
    recovered: int = 0
    released: int = 0
    failed: int = 0
    purged: int = 0

    def __str__(self) -> str:
        return (
            f"scanned={self.scanned} recovered={self.recovered} "
            f"released={self.released} failed={self.failed} purged={self.purged}"
        )


def reap_expired_leases(
    session: Session,
    store: LeaseStore,
    *,
    kind: str | None = None,
    limit: int = 100,
    purge_idle_seconds: float | None = None,
) -> ReapResult:
    """Recover every lapsed lease in one bounded cycle; return the tally.

    *kind* narrows the scan to one resource family (so a deployment can reap a slow domain
    on its own cadence), *limit* bounds the batch, and *purge_idle_seconds* — when given —
    also deletes free lease records untouched for that long, which is what keeps the table
    from growing once per row ever leased. Pass it comfortably above the longest TTL in the
    app: a purged record is re-created at epoch 1, which no surviving holder's stale epoch
    can match, but only if no live holder could still be pointing at it.
    """
    lapsed = store.expired(session, kind=kind, limit=limit)
    recovered = released = failed = 0
    for lease in lapsed:
        outcome = _recover_one(session, store, lease)
        if outcome == "recovered":
            recovered += 1
        elif outcome == "released":
            released += 1
        else:
            failed += 1
    purged = (
        store.purge(session, idle_seconds=purge_idle_seconds)
        if purge_idle_seconds is not None
        else 0
    )
    return ReapResult(
        scanned=len(lapsed),
        recovered=recovered,
        released=released,
        failed=failed,
        purged=purged,
    )


def _recover_one(session: Session, store: LeaseStore, lease: Lease) -> str:
    """Run *lease*'s registered recovery and forfeit it, atomically; name the outcome."""
    reaper = lease_reaper_for(lease.resource.kind)
    try:
        with enter_write_unit() as outermost:
            if reaper is not None:
                reaper(session, lease)
            store.forfeit(session, lease)
            if outermost:
                session.commit()  # arch-allow-mutations-emit-audit: closes the unit the domain's own audited _save already nested into, so recovery and forfeit land together — the audit record comes from the domain's service, not from here
    except Exception:
        # One domain's failing recovery must not abort the cycle for every other kind, and
        # the lease is deliberately left held-and-expired so the next cycle retries it.
        session.rollback()
        _logger.exception(
            "lease recovery failed; leaving the lease expired for the next cycle",
            extra={"lease_resource": str(lease.resource), "lease_holder": lease.holder},
        )
        return "failed"
    return "recovered" if reaper is not None else "released"


__all__ = ["ReapResult", "reap_expired_leases"]
