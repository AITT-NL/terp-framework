"""Realtime broker port + bounded in-process implementation.

The broker is the fan-out seam: publishers submit already-validated JSON and
each subscriber gets a bounded queue. A slow consumer is disconnected instead
of growing memory without bound; its transport observes ``BackpressureError``
and closes.

The in-process default reaches only subscribers in the process that published,
so it is right only while every publish and every subscriber share one process
(ADR 0176). A second replica breaks that, and so does a job handler running in
``terp jobs worker``: the worker serves no transport, so its publish reaches
nobody. Such a deployment installs a shared broker through ``configure_broker``
(``RedisRealtimeBroker`` from ``terp-cap-redis[realtime]``, or its own adapter
marked with :func:`mark_shared_broker`) and can promise it with
``configure_realtime(require_shared_broker=True)``.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from threading import RLock
from typing import TypeVar


class SubscriptionEnded(RuntimeError):
    """The broker ended a subscription, and its client must reconnect.

    A transport closes on it rather than failing the connection: the cause is the
    broker's (a consumer that fell behind, a shared backend that dropped the
    connection), never the client's request.
    """


class BackpressureError(SubscriptionEnded):
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
    async def publish(self, channel: str, payload: str) -> None:
        """Deliver *payload* to the channel's current subscribers, fire-and-forget.

        A publish usually rides a write path (a service, an ``_after_write`` hook, a job
        handler), so a broker whose backend is unreachable drops the message and logs it
        rather than failing the write it reports.
        """

    @abstractmethod
    def stream(self, channel: str) -> AsyncIterator[str]: ...

    async def subscribe(self, channel: str) -> AsyncIterator[str]:
        """Start a subscription now and return its messages.

        The transports call this before they answer the browser, so a subscription that
        cannot start is refused rather than reported as open (ADR 0176). A broker whose
        subscription can fail to start (a shared backend that is unreachable) overrides
        it to connect and subscribe before it returns, and raises
        :class:`SubscriptionEnded` when it cannot. The default returns :meth:`stream`,
        which subscribes at its first read.
        """
        return self.stream(channel)


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


_SHARED_BROKER_ATTR = "__terp_shared_realtime_broker__"

_Broker = TypeVar("_Broker", bound=RealtimeBroker)


def mark_shared_broker(broker: _Broker) -> _Broker:
    """Mark *broker* as shared across processes, and return it.

    Shared means a publish in any process reaches a subscriber in any other. The
    in-process default stays unmarked; ``require_shared_broker`` refuses it.
    """
    setattr(broker, _SHARED_BROKER_ATTR, True)
    return broker


def is_shared_broker(broker: RealtimeBroker | None) -> bool:
    """Return whether *broker* is marked as shared across processes."""
    return bool(getattr(broker, _SHARED_BROKER_ATTR, False))


class SharedBrokerRequiredError(RuntimeError):
    """A shared broker was promised, and the broker in force is per process."""


def _refuse_unshared(broker_type: type[RealtimeBroker]) -> None:
    raise SharedBrokerRequiredError(
        "configure_realtime(require_shared_broker=True) promises that a publish in any "
        f"process reaches a subscriber in any other, but the broker in force "
        f"({broker_type.__name__}) is per process. Install a shared one with "
        "configure_broker(RedisRealtimeBroker.from_url(...)) from terp-cap-redis[realtime], "
        "or mark your own adapter with mark_shared_broker(...) - or drop "
        "require_shared_broker if every publish and subscriber share one process."
    )


_configured_broker: RealtimeBroker | None = None
_shared_broker_required = False
_configuration_lock = RLock()


def configure_broker(broker: RealtimeBroker | None) -> None:
    """Install *broker* process-wide (``None`` resets to the lazy default).

    Refused at once when a shared broker is required and *broker* is not one.
    """
    global _configured_broker
    with _configuration_lock:
        if broker is not None and _shared_broker_required and not is_shared_broker(broker):
            _refuse_unshared(type(broker))
        _configured_broker = broker


def require_shared_broker(required: bool) -> None:
    """Record whether this deployment promised a shared broker.

    ``configure_realtime(require_shared_broker=...)`` is the public spelling. A broker
    already installed is checked now; the lazy default is checked when first used.
    """
    global _shared_broker_required
    with _configuration_lock:
        if required and _configured_broker is not None and not is_shared_broker(_configured_broker):
            _refuse_unshared(type(_configured_broker))
        _shared_broker_required = required


def get_broker() -> RealtimeBroker:
    """The configured broker, creating the bounded in-memory default lazily.

    Every publish and every transport reaches the broker through here, so a promised
    shared broker that was never installed fails the first use instead of
    publishing into a process nobody subscribes in. The refused default is never
    installed, so a ``configure_broker`` that comes later still keeps the promise.
    ``configure_broker`` and ``require_shared_broker`` refuse an installed per-process
    broker themselves, so the lazy default is the only one left to refuse here.
    """
    global _configured_broker
    with _configuration_lock:
        if _configured_broker is None:
            if _shared_broker_required:
                _refuse_unshared(InMemoryRealtimeBroker)
            _configured_broker = InMemoryRealtimeBroker()
        return _configured_broker


__all__ = [
    "BackpressureError",
    "InMemoryRealtimeBroker",
    "RealtimeBroker",
    "SharedBrokerRequiredError",
    "SubscriptionEnded",
    "audience_topic",
    "configure_broker",
    "get_broker",
    "is_shared_broker",
    "mark_shared_broker",
    "require_shared_broker",
]
