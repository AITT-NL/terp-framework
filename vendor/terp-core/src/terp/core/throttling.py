"""``ThrottleStore`` — the pluggable backend for rate limiting + login lockout (ADR 0036).

The request rate limiter and the per-account login throttle both keep two pieces of
state: a **fixed-window hit counter** and an optional **lock** that, once a threshold is
crossed, refuses a key for a cool-off window. Until now both kept that state in a
per-process dict, so a deployment running more than one worker diluted every limit by
the instance count (N instances ≈ N× the configured rate). This module factors the
state into a single small seam so a multi-instance deployment can plug a shared backend
(e.g. Redis) and get one correct global limit, while a single-process app keeps the
zero-dependency in-memory default unchanged.

Per ADR 0006, the seam is the full quadruple: a typed registry with a **safe default**
(:class:`InMemoryThrottleStore`), a **fail-closed** runtime control (a store that raises
makes the caller deny, never silently allow), a build-time/kernel test, and the existing
reason-bearing ``disabled`` opt-outs as the budgeted escape hatch. The default and its
per-instance behaviour are deliberately **unchanged**; a shared store is opt-in.
"""

from __future__ import annotations

import math
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Callable


class ThrottleStore(ABC):
    """A backend for fixed-window counters + lockouts, keyed by an opaque string.

    A single store may serve several controls (rate limit, login lockout); callers
    namespace their keys (``"rl:"`` / ``"lt:"`` prefixes) so they never collide. All
    times are integer seconds. An implementation must be safe for concurrent calls and
    must keep entries from growing without bound (expire on read or on a timer). A
    shared/remote implementation should let exceptions propagate: every call site treats
    a failing store as "deny" (fail-closed), so a backend outage can never silently lift
    a limit.
    """

    @abstractmethod
    def hit(self, key: str, window_seconds: int) -> tuple[int, int]:
        """Register one hit for *key*; return ``(count, reset_seconds)``.

        *count* is the number of hits in the current window (post-increment);
        *reset_seconds* is how long until the window rolls over. The window resets once
        ``window_seconds`` elapse since its first hit.
        """

    @abstractmethod
    def lock(self, key: str, seconds: int) -> None:
        """Lock *key* for *seconds* (a no-op caps are the caller's concern)."""

    @abstractmethod
    def locked(self, key: str) -> int:
        """Return the seconds *key* stays locked (``0`` when not locked)."""

    @abstractmethod
    def clear(self, key: str) -> None:
        """Drop the counter and any lock for *key* (e.g. on a success)."""


class InMemoryThrottleStore(ThrottleStore):
    """The default, per-process store — a dict guarded by a lock.

    This is the historical behaviour: state lives in one worker, so the limit is
    per-instance. Correct for a single process; a multi-worker deployment supplies a
    shared store instead. The clock is injectable for tests.
    """

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._hits: dict[str, tuple[float, int]] = {}
        self._locks: dict[str, float] = {}

    def hit(self, key: str, window_seconds: int) -> tuple[int, int]:
        now = self._clock()
        with self._lock:
            start, count = self._hits.get(key, (now, 0))
            if now - start >= window_seconds:
                start, count = now, 0
            count += 1
            self._hits[key] = (start, count)
        reset = max(1, math.ceil(window_seconds - (now - start)))
        return count, reset

    def lock(self, key: str, seconds: int) -> None:
        with self._lock:
            self._locks[key] = self._clock() + seconds

    def locked(self, key: str) -> int:
        now = self._clock()
        with self._lock:
            until = self._locks.get(key)
            if until is None:
                return 0
            if until <= now:
                del self._locks[key]
                return 0
            return max(1, int(until - now))

    def clear(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)
            self._locks.pop(key, None)

    def reset(self) -> None:
        """Drop all tracked state (a test seam; per-instance state otherwise persists)."""
        with self._lock:
            self._hits.clear()
            self._locks.clear()


# A marker stamped on a shared, multi-instance throttle backend (e.g. a Redis-backed
# store), so ``create_app(require_shared_throttle_store=True)`` can fail closed at boot
# when a per-instance store is wired by mistake. Mirrors the durable-audit-sink and
# token-revocation boot markers (a backend stamps it, the kernel boot guard checks it,
# neither imports the other). The default InMemoryThrottleStore is deliberately *unmarked*
# — the per-instance behaviour is unchanged unless a deployment opts in.
_SHARED_STORE_ATTR = "__terp_shared_throttle_store__"


def mark_shared_throttle_store(store: ThrottleStore) -> ThrottleStore:
    """Mark *store* as a shared, multi-instance backend, and return it.

    A horizontally scaled deployment wraps its shared backend with this so the boot guard
    accepts it; the per-instance default stays unmarked (and unchanged).
    """
    setattr(store, _SHARED_STORE_ATTR, True)
    return store


def is_shared_throttle_store(store: ThrottleStore | None) -> bool:
    """Return whether *store* is marked as a shared, multi-instance backend."""
    return bool(getattr(store, _SHARED_STORE_ATTR, False))


__all__ = [
    "InMemoryThrottleStore",
    "ThrottleStore",
    "is_shared_throttle_store",
    "mark_shared_throttle_store",
]
