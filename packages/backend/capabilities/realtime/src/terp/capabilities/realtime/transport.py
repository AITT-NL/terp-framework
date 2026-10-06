"""What both realtime transports do around the broker once a ticket is redeemed.

A transport subscribes before it answers (ADR 0176). An SSE ``200`` and a WebSocket
``accept`` both tell the browser it is subscribed, and the browser resets its reconnect
backoff on either, so a subscription that cannot start is refused instead: SSE answers
``503`` and a WebSocket closes ``1013`` before it is accepted, and the browser backs
off. The rest is the transports' shared plumbing: SSE framing, and settling the tasks a
WebSocket runs.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from fastapi import WebSocketDisconnect

from terp.core import AppError

from terp.capabilities.realtime.broker import SubscriptionEnded, audience_topic, get_broker


class RealtimeUnavailableError(AppError):
    """503 — the broker could not start the subscription; the client tries again later."""

    status_code = 503
    code = "realtime_unavailable"
    default_message = "Realtime updates are unavailable right now; try again later."


async def open_subscription(channel_name: str, audience: str) -> AsyncIterator[str]:
    """Subscribe to one channel audience now, before the transport reports success.

    A broker that cannot start the subscription raises :class:`SubscriptionEnded`,
    which becomes :class:`RealtimeUnavailableError` here. Anything else propagates as the
    error it is: a promised shared broker that was never installed is a wiring fault,
    not an outage to wait out.
    """
    broker = get_broker()
    topic = audience_topic(channel_name, audience)
    try:
        return await broker.subscribe(topic)
    except SubscriptionEnded as exc:
        raise RealtimeUnavailableError(log_context={"cause": str(exc)}) from exc


def _sse_data(payload: str) -> bytes:
    # The broker accepts only Pydantic-produced compact JSON; replace CR/LF as
    # defense in depth so one payload can never inject an SSE field/event.
    safe = payload.replace("\r", "").replace("\n", "")
    return f"data: {safe}\n\n".encode("utf-8")


def _raise_unexpected_task_results(results: list[object]) -> None:
    for result in results:
        if isinstance(result, BaseException) and not isinstance(
            result,
            (WebSocketDisconnect, SubscriptionEnded, asyncio.CancelledError),
        ):
            raise result


async def _settle_websocket_tasks(*tasks: asyncio.Task[None]) -> None:
    """Run until the first task settles, then cancel and drain the rest.

    The drain awaits ``asyncio.wait`` — never ``asyncio.gather``: when the
    host task is cancelled mid-drain (server shutdown, test-portal teardown),
    a cancelled gather re-raises the *last child's* CancelledError instead of
    the host's own. The child's copy carries no cancel-scope message, so the
    surrounding anyio cancel scope refuses to absorb it and the teardown
    crashes the connection task.
    """
    _done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    await asyncio.wait(tasks)
    results: list[object] = []
    for task in tasks:
        if task.cancelled():
            continue
        exc = task.exception()
        results.append(exc if exc is not None else task.result())
    _raise_unexpected_task_results(results)


__all__ = ["RealtimeUnavailableError", "open_subscription"]
