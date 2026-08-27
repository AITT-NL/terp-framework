"""terp.capabilities.leases — durable, fenced leases so a crashed worker's claim is recoverable.

The durable half of the lease seam (ADR 0095). :mod:`terp.core.leases` defines the
vocabulary — a resource, a holder, an epoch fence, an expiry, and the reaper registry a
domain fills — but deliberately ships **no** default store, because a per-process lease
would let two workers hold one resource. This capability is the store: one
``resource_lease`` row per leasable resource, in the app's own database, so taking a lease
commits atomically with the state change it protects.

What it gives an app:

* :class:`DatabaseLeaseStore` — wire it at ``create_app(lease_store=DatabaseLeaseStore())``
  and every ``terp.core`` lease call (``hold_lease`` / ``acquire_lease`` / ``renew_lease``
  / ``release_lease``) becomes real. It is marked durable, so
  ``create_app(require_durable_leases=True)`` accepts it.
* :func:`reap_expired_leases` and the declared :data:`LEASE_REAP` job — the cycle that
  runs each expired lease's registered recovery (``claimed`` → ``queued``, ``running`` →
  ``failed``) and forfeits the lease in one transaction. Put it on a cron with
  :func:`lease_reap_schedule`, or run ``terp leases reap``.
* the explicit :data:`module` — an admin read router plus "reap now", so a stuck claim is
  something an operator can *see* rather than something they have to be told about.
* :func:`holder_module` — the other audience, mounted separately because it is not an
  operator's. One endpoint, ``POST /{kind}/{key}/heartbeat``, so a holder that speaks HTTP
  rather than living in this process can prove liveness: without it a foreign worker had
  custody and no way to report, and its lease degraded to a plain deadline. Authenticated
  rather than ``ADMIN``, because the authorization that matters here is the app's own
  principal-to-holder mapping plus the epoch fence, and neither is a role.

It depends only on ``terp-core`` — never a sibling capability and never a broker engine.
Recipe: ``terp guide leases``.
"""

from __future__ import annotations

from terp.capabilities.leases.holder_router import (
    HolderResolver,
    build_holder_router,
    holder_module,
)
from terp.capabilities.leases.jobs import LEASE_REAP, LeaseReapPayload
from terp.capabilities.leases.models import ResourceLease
from terp.capabilities.leases.operations import (
    LEASES_HEARTBEAT,
    LEASES_LIST,
    LEASES_LIST_EXPIRED,
    LEASES_REAP,
)
from terp.capabilities.leases.reaper import ReapResult, reap_expired_leases
from terp.capabilities.leases.router import module, router
from terp.capabilities.leases.schedule import lease_reap_schedule
from terp.capabilities.leases.schemas import (
    LeaseHeartbeat,
    LeaseHeartbeatAccepted,
    LeaseReapReport,
    ResourceLeaseRead,
)
from terp.capabilities.leases.service import heartbeat, list_leases, reap_now
from terp.capabilities.leases.store import DatabaseLeaseStore

__all__ = [
    "LEASE_REAP",
    "DatabaseLeaseStore",
    "HolderResolver",
    "LEASES_HEARTBEAT",
    "LEASES_LIST",
    "LEASES_LIST_EXPIRED",
    "LEASES_REAP",
    "LeaseHeartbeat",
    "LeaseHeartbeatAccepted",
    "LeaseReapPayload",
    "LeaseReapReport",
    "ReapResult",
    "ResourceLease",
    "ResourceLeaseRead",
    "build_holder_router",
    "heartbeat",
    "holder_module",
    "lease_reap_schedule",
    "list_leases",
    "module",
    "reap_expired_leases",
    "reap_now",
    "router",
]
