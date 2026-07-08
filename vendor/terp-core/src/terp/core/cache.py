"""``CacheStore`` — the pluggable hot-read cache seam with a safe in-memory default.

An opt-in cache for hot reads: a module asks :func:`get_cache` for the configured
backend and reads/writes string values under namespaced keys with a mandatory TTL.
Until a deployment wires a shared backend (e.g. Redis) at ``create_app(cache_store=…)``,
the zero-dependency per-process :class:`InMemoryCacheStore` is the default — correct for
a single instance, and never a correctness dependency (a cache miss only costs a read).

Per ADR 0006 the seam is the proven quadruple, shaped exactly like the throttle store
(ADR 0036) it sits beside: a typed port with a **safe default**, a **fail-closed**
boot control (``create_app(require_shared_cache_store=True)`` refuses an unmarked
per-instance store, so a multi-instance deployment cannot silently ship N divergent
caches), the build-time kernel test, and the explicit opt-in as the escape hatch.
``terp.core`` is layer 0, so this module imports **no** cache engine — concrete
backends are opt-in capability packages a consumer wires at ``create_app(...)``.
"""

from __future__ import annotations

import math
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Callable


class CacheStore(ABC):
    """A string-value cache keyed by an opaque, caller-namespaced key.

    Values are serialized strings (the caller owns the encoding), so any backend —
    in-process dict, Redis, a managed cache — can implement the port without a
    pickle/marshalling contract. Every entry carries a TTL; there is no "cache
    forever". An implementation must be safe for concurrent calls and must keep
    entries from growing without bound (expire on read or on a timer). A cache is
    never load-bearing: a caller treats a raising or unavailable backend exactly
    like a miss and recomputes — never serves stale data past its TTL.
    """

    @abstractmethod
    def get(self, key: str) -> str | None:
        """Return the live value for *key*, or ``None`` on a miss / expired entry."""

    @abstractmethod
    def set(self, key: str, value: str, *, ttl_seconds: int) -> None:
        """Store *value* under *key* for *ttl_seconds* (must be positive)."""

    @abstractmethod
    def delete(self, key: str) -> None:
        """Drop *key* (a no-op when absent) — the invalidation hook after a write."""


class InMemoryCacheStore(CacheStore):
    """The default, per-process store — a dict guarded by a lock, TTL-expired on read/write.

    Correct for a single process; a multi-instance deployment supplies a shared
    backend instead (and marks it via :func:`mark_shared_cache_store`). The clock is
    injectable for tests.
    """

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: dict[str, tuple[float, str]] = {}
        self._next_sweep_at = -math.inf

    def get(self, key: str) -> str | None:
        now = self._clock()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if expires_at <= now:
                del self._entries[key]
                return None
            return value

    # How often (in clock seconds) a write may pay for a full expiry sweep. The sweep
    # scans every entry, so running it on *each* set would make writes O(live entries)
    # under the lock (~ms at 100k entries); gating it keeps writes O(1) amortized while
    # still bounding stale-entry buildup to one interval.
    _SWEEP_INTERVAL_SECONDS = 1.0

    def set(self, key: str, value: str, *, ttl_seconds: int) -> None:
        if ttl_seconds <= 0:
            raise ValueError(f"CacheStore.set requires a positive ttl_seconds, got {ttl_seconds!r}")
        now = self._clock()
        with self._lock:
            if now >= self._next_sweep_at:
                self._sweep_expired_locked(now)
                self._next_sweep_at = now + self._SWEEP_INTERVAL_SECONDS
            self._entries[key] = (now + ttl_seconds, value)

    def delete(self, key: str) -> None:
        with self._lock:
            self._entries.pop(key, None)

    def reset(self) -> None:
        """Drop all entries (a test seam; per-instance state otherwise persists)."""
        with self._lock:
            self._entries.clear()
            self._next_sweep_at = -math.inf

    def _sweep_expired_locked(self, now: float) -> None:
        """Drop expired entries while the caller holds ``_lock``."""
        expired = [key for key, (expires_at, _) in self._entries.items() if expires_at <= now]
        for key in expired:
            del self._entries[key]


# A marker stamped on a shared, multi-instance cache backend (e.g. a Redis-backed
# store), so ``create_app(require_shared_cache_store=True)`` can fail closed at boot
# when a per-instance store is wired by mistake. Mirrors the shared-throttle-store,
# durable-audit-sink, and durable-job boot markers (a backend stamps it, the kernel
# boot guard checks it, neither imports the other). The default InMemoryCacheStore is
# deliberately *unmarked* — per-instance caching is fine until a deployment opts in.
_SHARED_CACHE_ATTR = "__terp_shared_cache_store__"


def mark_shared_cache_store(store: CacheStore) -> CacheStore:
    """Mark *store* as a shared, multi-instance backend, and return it.

    A horizontally scaled deployment wraps its shared backend with this so the boot
    guard accepts it; the per-instance default stays unmarked (and unchanged).
    """
    setattr(store, _SHARED_CACHE_ATTR, True)
    return store


def is_shared_cache_store(store: CacheStore | None) -> bool:
    """Return whether *store* is marked as a shared, multi-instance backend."""
    return bool(getattr(store, _SHARED_CACHE_ATTR, False))


# The configured process-wide store. ``create_app`` calls ``configure_cache`` during
# boot; before that (or in a bare test) ``get_cache`` lazily falls back to a fresh
# in-memory default, so a module can always cache without a wiring dependency.
_configured_store: CacheStore | None = None


def configure_cache(store: CacheStore | None) -> None:
    """Install *store* as the process-wide cache (``None`` resets to the lazy default)."""
    global _configured_store
    _configured_store = store


def get_cache() -> CacheStore:
    """Return the configured cache, creating the in-memory default on first use."""
    global _configured_store
    if _configured_store is None:
        _configured_store = InMemoryCacheStore()
    return _configured_store


__all__ = [
    "CacheStore",
    "InMemoryCacheStore",
    "configure_cache",
    "get_cache",
    "is_shared_cache_store",
    "mark_shared_cache_store",
]
