"""Terp egress capability — the declared way out of the process.

``no_raw_outbound_http`` refuses ``httpx`` / ``requests`` / ``urllib.request`` /
``urllib3`` / ``aiohttp`` and the ``socket`` / ``http.client`` escape routes in
application code, and sends the author to "a declared capability with SSRF
protection". Until this package existed there was no such capability: the only guard in
the tree was private to webhook delivery, so the compliant path the rule named could
not be taken. A checked seam that does not cover the common case is a hole (ADR 0096
§4) — code goes around it, and the going-around is invisible to the gate.

A **library** capability, like ``terp-cap-leases``: no router, no table, no
auto-discovery entry point. Outbound access is not something an app should acquire by
installing a package; it is something it declares:

    from terp.capabilities.egress import EgressClient, EgressPolicy

    exchange = EgressClient(
        EgressPolicy(
            allowed_hosts=("api.exchange.example",),
            timeout_seconds=5.0,
        )
    )
    rates = exchange.get("https://api.exchange.example/v1/rates").content

The declaration is the point. An :class:`EgressPolicy` with no hosts permits nothing,
the timeout has no per-call override, every address is checked against the SSRF
denylist and the connection is pinned to the one that passed, and every attempt —
including a refusal — reaches the :class:`EgressAttempt` observer, which is where
metering and egress auditing attach.
"""

from __future__ import annotations

from terp.capabilities.egress.client import EgressClient, EgressResponse, Sender
from terp.capabilities.egress.errors import EgressFailedError, EgressRefusedError
from terp.capabilities.egress.policy import EgressAttempt, EgressPolicy, Observer
from terp.capabilities.egress.ssrf import (
    CLOUD_METADATA_ADDRESS,
    PinnedTarget,
    Resolver,
    as_ip_literal,
    is_denied_address,
    resolve_host,
)

__all__ = [
    "CLOUD_METADATA_ADDRESS",
    "EgressAttempt",
    "EgressClient",
    "EgressFailedError",
    "EgressPolicy",
    "EgressRefusedError",
    "EgressResponse",
    "Observer",
    "PinnedTarget",
    "Resolver",
    "Sender",
    "as_ip_literal",
    "is_denied_address",
    "resolve_host",
]
