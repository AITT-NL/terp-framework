"""``IdempotencyStore`` — the pluggable idempotency-key seam with a safe in-memory default.

Safe client retries for unsafe methods: a client stamps a mutating request with an
``Idempotency-Key`` header and may retry it (a timeout, a dropped connection, a crashed
client) without executing the mutation twice — the first execution's response is
stored and **replayed** to every retry of the same key. The middleware half lives in
``terp.core._internal.middleware`` (installed by ``create_app``, innermost in the
security stack); this module owns the storage port it coordinates through.

Per ADR 0006 the seam is the proven quadruple, shaped exactly like the throttle store
(ADR 0036) and the cache store beside it: a typed port with a **safe default** (the
zero-dependency per-process :class:`InMemoryIdempotencyStore` — correct for a single
instance), a **fail-closed** boot control
(``create_app(require_shared_idempotency_store=True)`` refuses an unmarked per-instance
store, so a multi-instance deployment cannot silently dedupe per worker), the
build-time kernel test, and the explicit opt-in as the escape hatch. ``terp.core`` is
layer 0, so this module imports **no** storage engine — a shared backend (e.g. Redis)
is an opt-in adapter a consumer wires at ``create_app(...)``.
"""

from __future__ import annotations

import math
import threading
import time
import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class StoredResponse:
    """The completed first response of an idempotent execution, kept for replay.

    *headers* are the application response's own headers (the middleware sits
    innermost, so per-request headers — request id, rate-limit counters, security
    headers — are re-added fresh by the outer stack on every replay).
    """

    status_code: int
    headers: tuple[tuple[str, str], ...]
    body: bytes


@dataclass(frozen=True)
class BeginOutcome:
    """What :meth:`IdempotencyStore.begin` found for a key (a tagged union).

    - ``"started"`` — the key is new; the caller owns the execution and must finish it
      with :meth:`~IdempotencyStore.complete` or :meth:`~IdempotencyStore.release`,
      authenticating with the returned *lease*.
    - ``"in_flight"`` — another request holds the key right now (a concurrent duplicate).
    - ``"replay"`` — the key completed earlier under the same fingerprint; *response*
      carries the stored response to hand back verbatim.
    - ``"mismatch"`` — the key exists but was begun under a **different** fingerprint
      (another method / path / caller / payload); replaying would answer a request
      that was never made, so the caller must refuse.
    """

    state: Literal["started", "in_flight", "replay", "mismatch"]
    lease: str | None = None
    response: StoredResponse | None = None


class IdempotencyStore(ABC):
    """Execution-dedup state keyed by an opaque, caller-scoped idempotency key.

    The contract is at-least-once-safe: :meth:`begin` must be **atomic** (two
    concurrent begins for one new key hand exactly one caller ``"started"``), a
    completed entry replays until its TTL lapses, and a lost / expired / evicted
    entry only costs a re-execution — never a wrong response. *fingerprint* is the
    request digest (method + path + caller + payload); a key reused under a
    different fingerprint is a ``"mismatch"``. An implementation must be safe for
    concurrent calls and must keep entries from growing without bound (expire on
    access or on a timer).
    """

    @abstractmethod
    def begin(self, key: str, fingerprint: str, *, ttl_seconds: int) -> BeginOutcome:
        """Claim *key* for execution, atomically; see :class:`BeginOutcome`."""

    @abstractmethod
    def complete(
        self, key: str, lease: str, response: StoredResponse, *, ttl_seconds: int
    ) -> None:
        """Store the finished *response* under *key* for *ttl_seconds* of replay.

        *lease* must match the one :meth:`begin` handed out — a stale lease (the
        entry expired mid-flight and was re-claimed) is discarded as a no-op, so a
        slow finisher can never clobber a newer execution.
        """

    @abstractmethod
    def release(self, key: str, lease: str) -> None:
        """Drop the in-flight claim on *key* so a retry may re-execute.

        Called when the execution failed (an exception, a 5xx) or its response is
        not storable. Lease-guarded like :meth:`complete`; a no-op when stale.
        """


@dataclass
class _Entry:
    expires_at: float
    fingerprint: str
    lease: str
    response: StoredResponse | None = None
    done: bool = False


class InMemoryIdempotencyStore(IdempotencyStore):
    """The default, per-process store — a dict guarded by a lock, TTL-expired on access.

    Correct for a single process; a multi-instance deployment supplies a shared
    backend instead (and marks it via :func:`mark_shared_idempotency_store`). Memory
    is bounded two ways: expired entries are swept (interval-gated, like the
    in-memory cache store), and *max_entries* caps the live set — on overflow the
    soonest-to-expire entry is evicted, which only weakens that key back to
    at-least-once (a retry re-executes), never to a wrong response. The clock is
    injectable for tests.
    """

    def __init__(
        self,
        *,
        max_entries: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_entries <= 0:
            raise ValueError(
                f"InMemoryIdempotencyStore requires a positive max_entries, got {max_entries!r}"
            )
        self._max_entries = max_entries
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: dict[str, _Entry] = {}
        self._next_sweep_at = -math.inf

    # How often (in clock seconds) a begin may pay for a full expiry sweep — the same
    # amortization as the in-memory cache store: a per-call scan would make begins
    # O(live entries) under the lock, so the sweep is interval-gated and stale-entry
    # buildup is bounded to one interval (each key's own expiry is still checked on
    # every access, so an expired entry is never served).
    _SWEEP_INTERVAL_SECONDS = 1.0

    def begin(self, key: str, fingerprint: str, *, ttl_seconds: int) -> BeginOutcome:
        if ttl_seconds <= 0:
            raise ValueError(
                f"IdempotencyStore.begin requires a positive ttl_seconds, got {ttl_seconds!r}"
            )
        now = self._clock()
        with self._lock:
            if now >= self._next_sweep_at:
                self._sweep_expired_locked(now)
                self._next_sweep_at = now + self._SWEEP_INTERVAL_SECONDS
            entry = self._entries.get(key)
            if entry is not None and entry.expires_at <= now:
                del self._entries[key]
                entry = None
            if entry is None:
                if len(self._entries) >= self._max_entries:
                    self._evict_soonest_expiring_locked()
                lease = uuid.uuid4().hex
                self._entries[key] = _Entry(
                    expires_at=now + ttl_seconds, fingerprint=fingerprint, lease=lease
                )
                return BeginOutcome(state="started", lease=lease)
            if entry.fingerprint != fingerprint:
                return BeginOutcome(state="mismatch")
            if not entry.done:
                return BeginOutcome(state="in_flight")
            return BeginOutcome(state="replay", response=entry.response)

    def complete(
        self, key: str, lease: str, response: StoredResponse, *, ttl_seconds: int
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError(
                f"IdempotencyStore.complete requires a positive ttl_seconds, got {ttl_seconds!r}"
            )
        now = self._clock()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None or entry.lease != lease:
                return  # stale lease — a newer claim owns the key now
            entry.expires_at = now + ttl_seconds
            entry.response = response
            entry.done = True

    def release(self, key: str, lease: str) -> None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and entry.lease == lease:
                del self._entries[key]

    def reset(self) -> None:
        """Drop all entries (a test seam; per-instance state otherwise persists)."""
        with self._lock:
            self._entries.clear()
            self._next_sweep_at = -math.inf

    def _sweep_expired_locked(self, now: float) -> None:
        """Drop expired entries while the caller holds ``_lock``."""
        expired = [key for key, entry in self._entries.items() if entry.expires_at <= now]
        for key in expired:
            del self._entries[key]

    def _evict_soonest_expiring_locked(self) -> None:
        """Evict the entry closest to its expiry while the caller holds ``_lock``."""
        victim = min(self._entries, key=lambda key: self._entries[key].expires_at)
        del self._entries[victim]


# A marker stamped on a shared, multi-instance idempotency backend (e.g. a
# Redis-backed store), so ``create_app(require_shared_idempotency_store=True)`` can
# fail closed at boot when a per-instance store is wired by mistake. Mirrors the
# shared-throttle-store, shared-cache-store, durable-audit-sink, and durable-job boot
# markers (a backend stamps it, the kernel boot guard checks it, neither imports the
# other). The default InMemoryIdempotencyStore is deliberately *unmarked* —
# per-instance dedup is fine until a deployment scales out and opts in.
_SHARED_IDEMPOTENCY_ATTR = "__terp_shared_idempotency_store__"


def mark_shared_idempotency_store(store: IdempotencyStore) -> IdempotencyStore:
    """Mark *store* as a shared, multi-instance backend, and return it.

    A horizontally scaled deployment wraps its shared backend with this so the boot
    guard accepts it; the per-instance default stays unmarked (and unchanged).
    """
    setattr(store, _SHARED_IDEMPOTENCY_ATTR, True)
    return store


def is_shared_idempotency_store(store: IdempotencyStore | None) -> bool:
    """Return whether *store* is marked as a shared, multi-instance backend."""
    return bool(getattr(store, _SHARED_IDEMPOTENCY_ATTR, False))


__all__ = [
    "BeginOutcome",
    "IdempotencyStore",
    "InMemoryIdempotencyStore",
    "StoredResponse",
    "is_shared_idempotency_store",
    "mark_shared_idempotency_store",
]
