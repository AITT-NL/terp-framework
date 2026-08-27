"""Operation declarations for the ``leases`` capability's routes.

Each route below declares what it does in plain English (ADR 0102), so a
non-technical reader can see the effect of viewing lease state, reaping
expired leases, or renewing a holder's claim, without having to read HTTP
verbs and paths.
"""

from __future__ import annotations

from terp.core import OperationDefinition

LEASES_LIST = OperationDefinition(
    id="leases.list_resource_leases", label="List the active resource leases"
)
LEASES_LIST_EXPIRED = OperationDefinition(
    id="leases.list_expired_resource_leases", label="List the leases that have expired"
)
LEASES_REAP = OperationDefinition(
    id="leases.reap_expired_now", label="Clean up expired leases right now"
)
LEASES_HEARTBEAT = OperationDefinition(
    id="leases.send_heartbeat", label="Renew a lease holder's claim on a resource"
)

__all__ = [
    "LEASES_HEARTBEAT",
    "LEASES_LIST",
    "LEASES_LIST_EXPIRED",
    "LEASES_REAP",
]
