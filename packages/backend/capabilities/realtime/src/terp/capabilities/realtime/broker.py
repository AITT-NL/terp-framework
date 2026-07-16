"""Realtime broker port + bounded in-process implementation.

The broker is the fan-out seam: publishers submit already-validated JSON and
each subscriber gets a bounded queue. A slow consumer is disconnected instead
of growing memory without bound; its transport observes ``BackpressureError``
and closes. Multi-replica deployments replace this per-process adapter with a
shared broker (Redis/pubsub, managed messaging) through ``configure_broker``.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from threading import RLock


class BackpressureError(RuntimeError):
    """A subscriber fell behind its bounded queue and must reconnect."""


def audience_topic(channel: str, audience: str) -> str:
    """Opaque broker topic for one declared channel + authorized audience."""
    normalized = audience.strip()
    if not normalized or len(normalized) > 500 or "\x00" in normalized:
        raise ValueError("realtime audience must be a non-empty string (max 500 chars)")
    return f"{channel}\x00{normalized}"


@dataclass(frozen=True)
class _Overflow:
    pass


_OVERFLOW = _Overflow()


class RealtimeBroker(ABC):
    """Publish validated JSON and subscribe to one declared channel name."""

    @abstractmethod
    async def publish(self, channel: str, payload: str) -> None: ...

    @abstractmethod
    def stream(self, channel: str) -> AsyncIterator[str]: ...


@dataclass(eq=False)
class _Subscriber:
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue[str | _Overflow]


class InMemoryRealtimeBroker(RealtimeBroker):
    """Thread-safe, per-process fan-out with bounded queues.

    ``publish`` may run on an event loop different from a subscriber's (or be
    invoked via ``asyncio.run`` from a sync service hook), so delivery uses
    ``call_soon_threadsafe`` into the queue owner's loop. Queue overflow posts
    one terminal marker and unregisters the subscriber.
    """

    def __init__(self, *, queue_size: int = 100) -> None:
        if queue_size <= 0:
            raise ValueError("realtime queue_size must be positive")
        self._queue_size = queue_size
        self._lock = RLock()
        self._subscribers: dict[str, set[_Subscriber]] = {}

    async def publish(self, channel: str, payload: str) -> None:
        with self._lock:
            subscribers = tuple(self._subscribers.get(channel, ()))
        for subscriber in subscribers:
            subscriber.loop.call_soon_threadsafe(
                self._deliver, channel, subscriber, payload
            )

    def stream(self, channel: str) -> AsyncIterator[str]:
        return self._subscription(channel)

    async def _subscription(self, channel: str) -> AsyncIterator[str]:
        subscriber = _Subscriber(
            loop=asyncio.get_running_loop(),
            queue=asyncio.Queue(maxsize=self._queue_size),
        )
        with self._lock:
            self._subscribers.setdefault(channel, set()).add(subscriber)
        try:
            while True:
                item = await subscriber.queue.get()
                if item is _OVERFLOW:
                    raise BackpressureError(
                        f"realtime subscriber for {channel!r} exceeded its queue"
                    )
                yield item
        finally:
            self._discard(channel, subscriber)

    def _deliver(self, channel: str, subscriber: _Subscriber, payload: str) -> None:
        try:
            subscriber.queue.put_nowait(payload)
        except asyncio.QueueFull:
            self._discard(channel, subscriber)
            while not subscriber.queue.empty():
                subscriber.queue.get_nowait()
            subscriber.queue.put_nowait(_OVERFLOW)

    def _discard(self, channel: str, subscriber: _Subscriber) -> None:
        with self._lock:
            subscribers = self._subscribers.get(channel)
            if subscribers is None:
                return
            subscribers.discard(subscriber)
            if not subscribers:
                self._subscribers.pop(channel, None)

    def reset(self) -> None:
        """Drop every subscriber (test-isolation seam)."""
        with self._lock:
            self._subscribers.clear()


_configured_broker: RealtimeBroker | None = None
_configuration_lock = RLock()


def configure_broker(broker: RealtimeBroker | None) -> None:
    """Install *broker* process-wide (``None`` resets to the lazy default)."""
    global _configured_broker
    with _configuration_lock:
        _configured_broker = broker


def get_broker() -> RealtimeBroker:
    """The configured broker, creating the bounded in-memory default lazily."""
    global _configured_broker
    with _configuration_lock:
        if _configured_broker is None:
            _configured_broker = InMemoryRealtimeBroker()
        return _configured_broker


__all__ = [
    "BackpressureError",
    "InMemoryRealtimeBroker",
    "RealtimeBroker",
    "audience_topic",
    "configure_broker",
    "get_broker",
]
