"""Admin router for leases: who holds what, what has lapsed, and "reap now".

Leases are taken by workers, so this is an **operator's window**, not a client API. It
answers the two questions that a lease exists to make answerable at all — *is this work
still being done?* and *what is stuck?* — and offers the one safe corrective action.

Three endpoints, deliberately:

* ``GET /`` — every lease record, most-recently-touched first, each with an ``expired``
  flag decided against one clock for the whole page.
* ``GET /expired`` — the triage view: exactly what the next reap cycle will act on.
* ``POST /reap`` — run one cycle now. It touches only **already-lapsed** leases, so it
  cannot take work away from a holder that is still reporting, and running it twice is a
  no-op. There is no force-release endpoint: stealing a live lease is the split brain the
  fence exists to prevent, and an endpoint for it would be a permanent invitation.

All three are privileged operational data, so the policy requires ``ADMIN``. Like the sync
capability, ``leases`` declares **no** ``terp.capabilities`` entry point: leasing does
nothing until an app wires a store, so the app mounts this ``module`` explicitly
(``create_app(specs=[..., leases.module], lease_store=DatabaseLeaseStore())``). Mounting it
registers the ``LEASE_REAP`` job (``ModuleSpec.jobs``).
"""

from __future__ import annotations

from fastapi import APIRouter

from terp.core import (
    ADMIN,
    ModuleSpec,
    Page,
    PaginationDep,
    Policy,
    SessionDep,
    operation,
)

from terp.capabilities.leases.jobs import LEASE_REAP
from terp.capabilities.leases.operations import (
    LEASES_LIST,
    LEASES_LIST_EXPIRED,
    LEASES_REAP,
)
from terp.capabilities.leases.schemas import LeaseReapReport, ResourceLeaseRead
from terp.capabilities.leases.service import list_leases, reap_now

router = APIRouter(tags=["leases"])


@router.get("/", response_model=Page[ResourceLeaseRead])
@operation(LEASES_LIST)
def list_resource_leases(
    session: SessionDep,
    pagination: PaginationDep,
    kind: str | None = None,
) -> Page[ResourceLeaseRead]:
    rows, total, now = list_leases(session, pagination=pagination, kind=kind)
    return Page[ResourceLeaseRead].of(
        [ResourceLeaseRead.of(row, now=now) for row in rows], total, pagination
    )


@router.get("/expired", response_model=Page[ResourceLeaseRead])
@operation(LEASES_LIST_EXPIRED)
def list_expired_resource_leases(
    session: SessionDep,
    pagination: PaginationDep,
    kind: str | None = None,
) -> Page[ResourceLeaseRead]:
    rows, total, now = list_leases(
        session, pagination=pagination, kind=kind, expired_only=True
    )
    return Page[ResourceLeaseRead].of(
        [ResourceLeaseRead.of(row, now=now) for row in rows], total, pagination
    )


@router.post("/reap", response_model=LeaseReapReport)
@operation(LEASES_REAP)
def reap_expired_now(
    session: SessionDep,
    kind: str | None = None,
    limit: int = 100,
) -> LeaseReapReport:
    result = reap_now(session, kind=kind, limit=limit)
    return LeaseReapReport(
        scanned=result.scanned,
        recovered=result.recovered,
        released=result.released,
        failed=result.failed,
        purged=result.purged,
    )


module = ModuleSpec(
    name="leases",
    router=router,
    jobs=(LEASE_REAP,),
    policy=Policy(read=ADMIN, write=ADMIN),
)


__all__ = ["module", "router"]
