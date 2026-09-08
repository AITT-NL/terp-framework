"""Operation declarations for the ``realtime`` capability's routes.

Each route below declares what it does in plain English (ADR 0102), so a
non-technical reader can see the effect of minting a connection pass or
opening a live update stream, without having to read HTTP verbs and paths.
"""

from __future__ import annotations

from terp.core import OperationDefinition

REALTIME_MINT_TICKET = OperationDefinition(
    id="realtime.mint_ticket",
    label="Create a short-lived pass that lets someone open a live connection",
)
REALTIME_SUBSCRIBE_SSE = OperationDefinition(
    id="realtime.subscribe_sse",
    label="Start streaming live updates for one channel",
)
REALTIME_SUBSCRIBE_WEBSOCKET = OperationDefinition(
    id="realtime.subscribe_websocket",
    label="Open a two-way live connection to one channel",
)

#: Every operation this capability's routes declare, in route order.
#:
#: An app folds the capability into its :class:`~terp.core.OperationCatalog` by
#: splatting this (``*REALTIME_OPERATIONS``) rather than naming each constant, so a
#: release that adds a route here cannot refuse a ``STRICT`` app's boot (ADR 0124).
#: Held exhaustive against the router by
#: ``tests/architecture/test_capability_operations.py``.
REALTIME_OPERATIONS: tuple[OperationDefinition, ...] = (
    REALTIME_MINT_TICKET,
    REALTIME_SUBSCRIBE_SSE,
    REALTIME_SUBSCRIBE_WEBSOCKET,
)

__all__ = [
    "REALTIME_MINT_TICKET",
    "REALTIME_OPERATIONS",
    "REALTIME_SUBSCRIBE_SSE",
    "REALTIME_SUBSCRIBE_WEBSOCKET",
]
