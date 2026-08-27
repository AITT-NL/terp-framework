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

__all__ = ["REALTIME_MINT_TICKET", "REALTIME_SUBSCRIBE_SSE"]
