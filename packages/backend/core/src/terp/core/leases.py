"""``LeaseStore`` — expiring, fenced custody of work a worker might not live to finish.

A worker takes a piece of work: it flips a row to ``claimed``, or opens a ``running``
run, and starts. Then it is killed — OOM, a rescheduled pod, a lost network. The row it
took stays taken. Nothing in the schema records *who* took it or *until when*, so nothing
can tell "still working" from "died three hours ago", and the only recovery is a
hand-written ``UPDATE``. Every queue-shaped table rediscovers this, and the second half —
"at most one worker per pipeline / per source / per connection" — is the same missing
primitive read from the other side.

A **lease** is that primitive: a named resource, held by an opaque *holder*, until an
explicit *expiry*, fenced by a monotonically increasing *epoch*. Three properties earn
each of those words:

* **Expiry** turns a crash into a timeout. A holder that stops heartbeating loses the
  resource at ``expires_at`` without anyone having to decide that it died.
* **The epoch is a fence.** A holder proves ownership with ``(holder, epoch)``, so a
  process that was paused past its expiry — and whose resource was granted to a
  successor — cannot renew, release or report: its epoch is stale and every write is
  refused. Without a fence, expiry alone lets a zombie clobber its successor.
* **The reaper closes the loop.** Expiry frees the *resource*; it does not walk the
  *domain row* back. A domain registers a :data:`LeaseReaper` per resource kind
  (:func:`register_lease_reaper`) — the one piece only the domain can write — and the
  reaper runs it, so ``claimed`` becomes ``queued`` again, or a ``running`` run is closed
  ``failed``, through the domain's own audited service.

Why the operations take a ``Session``. A lease is only correct if taking it is atomic
with the state change it protects: claim-the-row and take-the-lease must commit or roll
back together, or a crash between them re-creates the very orphan the lease exists to
prevent. So the store writes on the **caller's** session, exactly like
:func:`terp.core.enqueue` on a durable queue — one transaction, one outcome.

In practice that means taking the lease from inside the service's own write, which is what
``_after_write`` is for::

    class RequestService(BaseService[RunRequest, ...]):
        def _after_write(self, session, entity, action):
            if entity.status == CLAIMED:
                hold_lease(
                    session,
                    LeaseResource.for_row(entity),
                    holder=self._worker_id,
                    ttl_seconds=60,
                )

The refusal then does the right thing for free: a resource somebody else holds raises
:class:`LeaseHeldError` *inside* the write unit, so the row never reaches ``claimed`` at
all — no compensating update, no window where the two disagree.

Why there is **no default store**. Every other store seam here (idempotency, throttle,
cache) ships a safe in-process default, because degrading one costs a re-execution or a
cache miss. Degrading a lease costs *two workers running the same work at once* — the one
thing the lease exists to prevent — so a per-process default would not weaken this seam,
it would silently fail to deliver it. ``None`` is therefore the default and
:func:`acquire_lease` fails closed with :class:`LeaseError` until an app names a store:
``create_app(lease_store=DatabaseLeaseStore())`` (``terp-cap-leases``, which keeps leases
in the same database as the rows they protect, so the atomicity above actually holds).
:class:`InMemoryLeaseStore` exists for tests and single-process development and is
deliberately **unmarked**, so ``create_app(require_durable_leases=True)`` refuses it.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Final

from sqlmodel import Session

from terp.core.errors import ConflictError
from terp.core.runtime import register_runtime_seam

# Hard caps mirroring the durable table's columns, validated here so an oversized value
# fails in Python with a message that names the field — never mid-transaction on a
# backend that enforces ``VARCHAR(n)`` while SQLite quietly accepted it in the tests.
LEASE_KIND_MAX: Final[int] = 64
LEASE_KEY_MAX: Final[int] = 200
LEASE_HOLDER_MAX: Final[int] = 128

# How much of a lease must elapse before :meth:`LeaseGuard.heartbeat` actually writes.
# A heartbeat is called from inside a work loop (per record, per batch), so an
# unconditional UPDATE would turn a lease into a write-amplification source; renewing
# once past the half-way mark keeps one renewal in flight per lease and leaves a full
# half-TTL of slack for the write to land.
_RENEW_AFTER_FRACTION: Final[float] = 0.5


def _utc_now() -> datetime:
    """UTC ``now`` provider — the default clock, injectable on every store for tests."""
    return datetime.now(UTC)


class LeaseError(RuntimeError):
    """Raised when the lease seam is used without a configured store (fail closed).

    Not an :class:`~terp.core.AppError`: reaching a lease operation with no store wired
    is a composition mistake, like enqueuing an unregistered job
    (:class:`~terp.core.JobError`) — it must surface as a boot / wiring bug, not as an
    HTTP status a client could learn to retry.
    """


class LeaseHeldError(ConflictError):
    """409 — the resource is leased by someone else and that lease has not expired."""

    code = "lease_held"
    default_message = "This work is already being processed. Try again shortly."


class LeaseLostError(ConflictError):
    """409 — the caller's lease expired (or was re-granted); it may no longer write.

    The fail-closed half of the fence: a holder that has been superseded is told to stop
    rather than allowed to finish over the top of its successor.
    """

    code = "lease_lost"
    default_message = "This work was taken over because its lease expired."


@dataclass(frozen=True)
class LeaseResource:
    """What is being leased: a *kind* (the family) and a *key* (the one thing).

    Two shapes cover every case the seam was built for, and both are just strings, so a
    lease is never coupled to a table:

    * a **row** — ``LeaseResource.for_row(run)`` yields ``("sync_run", "<uuid>")``, the
      "reap this stale claim" case;
    * a **domain mutex** — ``LeaseResource("pipeline", str(pipeline_id))``, the "at most
      one active run per pipeline" case, which no row-shaped lease can express, because
      the thing being serialised is not a row.

    The *kind* is also the reaper key (:func:`register_lease_reaper`), so it names a
    recovery policy as much as a resource family — keep it stable, it is persisted.
    """

    kind: str
    key: str

    def __post_init__(self) -> None:
        for field, value, limit in (
            ("kind", self.kind, LEASE_KIND_MAX),
            ("key", self.key, LEASE_KEY_MAX),
        ):
            if not value or not value.strip():
                raise ValueError(f"LeaseResource.{field} must be a non-empty string")
            if len(value) > limit:
                raise ValueError(
                    f"LeaseResource.{field} is {len(value)} characters, exceeding its "
                    f"{limit}-character column bound"
                )

    @classmethod
    def for_row(cls, row: object) -> LeaseResource:
        """The lease resource identifying *row*: its table name plus its primary key.

        The convenience constructor for the row-custody case. It reads ``__tablename__``
        and ``id`` off the model, so the resource stays stable across processes without
        anyone inventing a key format — and a non-table object is refused here rather
        than persisting a lease nothing can ever be matched against.
        """
        table = getattr(row, "__tablename__", None)
        identifier = getattr(row, "id", None)
        if not isinstance(table, str) or identifier is None:
            raise TypeError(
                "LeaseResource.for_row needs a table model with __tablename__ and id, "
                f"got {type(row).__name__}"
            )
        return cls(kind=table, key=str(identifier))

    def __str__(self) -> str:
        return f"{self.kind}:{self.key}"


@dataclass(frozen=True)
class Lease:
    """A granted lease: the fenced, expiring proof that *holder* owns *resource*.

    Immutable — a renewal returns a **new** ``Lease`` with a later ``expires_at`` (and the
    same ``epoch``), so a stale value can never be mistaken for a current one by having
    been mutated underneath a caller.
    """

    resource: LeaseResource
    holder: str
    epoch: int
    expires_at: datetime

    def is_expired(self, now: datetime) -> bool:
        """Whether this lease has lapsed at *now* (the boundary counts as expired)."""
        return self.expires_at <= now

    def remaining(self, now: datetime) -> timedelta:
        """How much of the lease is left at *now* (never negative)."""
        return max(self.expires_at - now, timedelta(0))


class LeaseStore(ABC):
    """Where leases live. An implementation must be correct under real concurrency.

    The contract every method is held to:

    * :meth:`acquire` is **atomic** — two workers racing for one free resource hand
      exactly one of them a lease — and it grants a resource whose lease has expired,
      bumping ``epoch`` on every grant.
    * :meth:`renew` / :meth:`release` / :meth:`forfeit` are **fenced**: they take effect
      only for the exact ``(holder, epoch)`` recorded, and are a no-op (returning ``None``
      / ``False``) for a superseded holder.
    * :meth:`renew` refuses an **already-expired** lease rather than resurrecting it; the
      resource may already belong to a successor, and reviving it would be the split brain
      the fence exists to stop.
    * :meth:`expired` is the reaper's input and must be bounded (*limit*), so a backlog
      never turns one reap cycle into an unbounded transaction.

    Every write lands on the caller's ``session``, so a claim and the state change it
    protects commit together (see the module docstring).
    """

    #: The store's clock. Injectable so a test can advance time without sleeping.
    clock: Callable[[], datetime] = staticmethod(_utc_now)

    @abstractmethod
    def acquire(
        self, session: Session, resource: LeaseResource, *, holder: str, ttl_seconds: float
    ) -> Lease | None:
        """Lease *resource* to *holder* for *ttl_seconds*, or ``None`` if it is held."""

    @abstractmethod
    def renew(self, session: Session, lease: Lease, *, ttl_seconds: float) -> Lease | None:
        """Extend *lease* by *ttl_seconds*, or ``None`` if it was lost (fenced out)."""

    @abstractmethod
    def release(self, session: Session, lease: Lease) -> bool:
        """Give the resource back early; ``False`` when *lease* no longer holds it."""

    @abstractmethod
    def expired(
        self, session: Session, *, kind: str | None = None, limit: int = 100
    ) -> tuple[Lease, ...]:
        """Up to *limit* still-held leases whose expiry has passed (the reaper's input)."""

    @abstractmethod
    def forfeit(self, session: Session, lease: Lease) -> bool:
        """Clear an expired *lease* after its reaper ran; ``False`` if already re-granted."""

    @abstractmethod
    def purge(self, session: Session, *, idle_seconds: float) -> int:
        """Delete free lease records untouched for *idle_seconds*; return the count.

        A lease record outlives its lease: releasing one frees the resource but leaves the
        record, and a *row*-shaped resource is never leased twice — so without this the
        table would grow once per row ever processed. Purging only **free** records idle
        far longer than any TTL is safe under the fence: a resurrected record starts at
        epoch 1, which no surviving holder's stale epoch can match.
        """


@dataclass
class _Entry:
    """One in-memory lease record: the holder, its fence, and when it lapses."""

    holder: str | None
    epoch: int
    expires_at: datetime | None
    touched_at: datetime


class InMemoryLeaseStore(LeaseStore):
    """A per-process store — **for tests and single-process development only**.

    It honours the whole contract (atomic under threads, fenced, expiring) within one
    process, and is therefore useless for the failure it exists to handle: the state dies
    with the process that crashed, so nothing survives to be reaped, and two replicas
    would each believe they hold the same resource. It is deliberately **unmarked**, so
    ``create_app(require_durable_leases=True)`` refuses it — wire ``terp-cap-leases``'
    ``DatabaseLeaseStore`` anywhere a lease must outlive its holder. ``session`` is
    accepted and ignored (there is no transaction to join).
    """

    def __init__(self, *, clock: Callable[[], datetime] = _utc_now) -> None:
        self.clock = clock
        self._lock = threading.Lock()
        self._entries: dict[LeaseResource, _Entry] = {}

    def acquire(
        self, session: Session, resource: LeaseResource, *, holder: str, ttl_seconds: float
    ) -> Lease | None:
        _validate_holder(holder)
        _validate_ttl(ttl_seconds)
        now = self.clock()
        with self._lock:
            entry = self._entries.get(resource)
            if (
                entry is not None
                and entry.holder is not None
                and entry.expires_at is not None
                and entry.expires_at > now
            ):
                return None
            epoch = (entry.epoch if entry is not None else 0) + 1
            expires_at = now + timedelta(seconds=ttl_seconds)
            self._entries[resource] = _Entry(
                holder=holder, epoch=epoch, expires_at=expires_at, touched_at=now
            )
            return Lease(resource=resource, holder=holder, epoch=epoch, expires_at=expires_at)

    def renew(self, session: Session, lease: Lease, *, ttl_seconds: float) -> Lease | None:
        _validate_ttl(ttl_seconds)
        now = self.clock()
        with self._lock:
            entry = self._entries.get(lease.resource)
            if entry is None or not self._still_holds(entry, lease):
                return None
            if entry.expires_at is None or entry.expires_at <= now:
                return None
            expires_at = now + timedelta(seconds=ttl_seconds)
            entry.expires_at = expires_at
            entry.touched_at = now
            return replace(lease, expires_at=expires_at)

    def release(self, session: Session, lease: Lease) -> bool:
        with self._lock:
            entry = self._entries.get(lease.resource)
            if entry is None or not self._still_holds(entry, lease):
                return False
            entry.holder = None
            entry.expires_at = None
            entry.touched_at = self.clock()
            return True

    def expired(
        self, session: Session, *, kind: str | None = None, limit: int = 100
    ) -> tuple[Lease, ...]:
        _validate_limit(limit)
        now = self.clock()
        with self._lock:
            found = [
                Lease(
                    resource=resource,
                    holder=entry.holder,
                    epoch=entry.epoch,
                    expires_at=entry.expires_at,
                )
                for resource, entry in self._entries.items()
                if entry.holder is not None
                and entry.expires_at is not None
                and entry.expires_at <= now
                and (kind is None or resource.kind == kind)
            ]
        found.sort(key=lambda item: (item.expires_at, str(item.resource)))
        return tuple(found[:limit])

    def forfeit(self, session: Session, lease: Lease) -> bool:
        # Not simply ``release``: forfeiting is the reaper's tool and must be unable to take
        # a *live* lease away from a holder that is still reporting. The expiry condition is
        # what makes that structural rather than a promise the caller has to keep.
        with self._lock:
            entry = self._entries.get(lease.resource)
            if entry is None or not self._still_holds(entry, lease):
                return False
            if entry.expires_at is None or entry.expires_at > self.clock():
                return False
            entry.holder = None
            entry.expires_at = None
            entry.touched_at = self.clock()
            return True

    def purge(self, session: Session, *, idle_seconds: float) -> int:
        _validate_ttl(idle_seconds)
        cutoff = self.clock() - timedelta(seconds=idle_seconds)
        with self._lock:
            stale = [
                resource
                for resource, entry in self._entries.items()
                if entry.holder is None and entry.touched_at < cutoff
            ]
            for resource in stale:
                del self._entries[resource]
        return len(stale)

    def reset(self) -> None:
        """Drop every lease (a test seam; per-instance state otherwise persists)."""
        with self._lock:
            self._entries.clear()

    @staticmethod
    def _still_holds(entry: _Entry, lease: Lease) -> bool:
        """Whether *entry* is still the exact ``(holder, epoch)`` grant *lease* records."""
        return entry.holder == lease.holder and entry.epoch == lease.epoch


def _validate_holder(holder: str) -> None:
    """Refuse an empty or over-long holder id before it reaches a bounded column."""
    if not holder or not holder.strip():
        raise ValueError("a lease holder must be a non-empty string")
    if len(holder) > LEASE_HOLDER_MAX:
        raise ValueError(
            f"lease holder is {len(holder)} characters, exceeding its "
            f"{LEASE_HOLDER_MAX}-character column bound"
        )


def _validate_ttl(ttl_seconds: float) -> None:
    """Refuse a non-positive TTL: a lease that is born expired protects nothing."""
    if ttl_seconds <= 0:
        raise ValueError(
            f"a lease ttl must be a positive number of seconds, got {ttl_seconds!r}"
        )


def _validate_limit(limit: int) -> None:
    """Refuse a non-positive batch bound, so a reap cycle always makes progress."""
    if limit <= 0:
        raise ValueError(f"a lease batch limit must be positive, got {limit!r}")


# --------------------------------------------------------------------------- #
# The reaper registry — the domain's half of expiry (a capability registration)
# --------------------------------------------------------------------------- #

# What to do about the *domain* when a lease expires: walk the row back to a state a
# retry can pick up. It runs inside the reap transaction, so it must write through the
# domain's own audited service (its recovery lands in the audit trail like any other
# mutation) and it must be idempotent — at-least-once applies to reaping too.
LeaseReaper = Callable[[Session, Lease], None]

_reapers: dict[str, LeaseReaper] = {}


def register_lease_reaper(kind: str, reaper: LeaseReaper) -> None:
    """Register the recovery for expired leases of *kind* (called at import / wiring).

    A capability registration, not per-app runtime — like a scope predicate it is
    installed by the code that owns the resource kind and is meant to outlive a composed
    app. Registration is idempotent for the same callable and refuses a second, different
    one: two recoveries for one kind would make reaping order-dependent, and which reaper
    won would decide whether a stale run is retried or failed.
    """
    if not kind or not kind.strip():
        raise ValueError("a lease reaper must be registered for a non-empty kind")
    existing = _reapers.get(kind)
    if existing is not None and existing is not reaper:
        raise ValueError(f"a lease reaper for kind {kind!r} is already registered")
    _reapers[kind] = reaper


def lease_reaper_for(kind: str) -> LeaseReaper | None:
    """The registered recovery for *kind*, or ``None`` when the domain declared none."""
    return _reapers.get(kind)


def registered_lease_reapers() -> Mapping[str, LeaseReaper]:
    """Every registered reaper, keyed by resource kind (read-only)."""
    return MappingProxyType(dict(_reapers))


def reset_lease_reapers() -> None:
    """Clear the registry (a test seam; owners re-register at import)."""
    _reapers.clear()


# --------------------------------------------------------------------------- #
# The per-app runtime seam
# --------------------------------------------------------------------------- #

_active_store: LeaseStore | None = None


def configure_leases(store: LeaseStore | None = None) -> None:
    """Install the active lease *store* (called by ``create_app``).

    ``None`` — the default — leaves the seam unconfigured, so an app that never wires a
    store cannot silently get per-process leases; the first lease call fails closed with
    :class:`LeaseError` instead. Mirrors :func:`terp.core.configure_jobs`.
    """
    global _active_store
    _active_store = store


def active_lease_store() -> LeaseStore | None:
    """The installed store, or ``None`` when this app wired none.

    A capability that leases *optionally* — running unleased exactly as it did before —
    checks this rather than catching :class:`LeaseError`, so "no store configured" stays a
    wiring answer and is never confused with a real failure mid-work.
    """
    return _active_store


def reset_leases_runtime() -> None:
    """Restore the unconfigured seam (the composition-root / test baseline).

    The reaper registry is a *capability* registration and is deliberately not cleared
    here — it has its own :func:`reset_lease_reapers`, exactly as the job tenant-context
    seam and the scope predicates do.
    """
    global _active_store
    _active_store = None


def _capture_leases_runtime() -> LeaseStore | None:
    """Snapshot the installed store (the runtime-seam capture hook)."""
    return _active_store


def _restore_leases_runtime(state: LeaseStore | None) -> None:
    """Put back a store snapshot taken by :func:`_capture_leases_runtime`."""
    global _active_store
    _active_store = state


register_runtime_seam(
    "leases",
    capture=_capture_leases_runtime,
    restore=_restore_leases_runtime,
    reset=reset_leases_runtime,
)


# A marker stamped on a store whose leases outlive the process holding them, so
# ``create_app(require_durable_leases=True)`` can fail closed at boot when the in-memory
# store is wired by mistake. Mirrors the durable-job-queue and shared-idempotency
# markers: a backend stamps it, the kernel boot guard checks it, neither imports the other.
_DURABLE_LEASE_ATTR: Final[str] = "__terp_durable_lease_store__"


def mark_durable_lease_store(store: LeaseStore) -> LeaseStore:
    """Mark *store* as one whose leases survive the holder's process, and return it."""
    setattr(store, _DURABLE_LEASE_ATTR, True)
    return store


def is_durable_lease_store(store: LeaseStore | None) -> bool:
    """Return whether *store* is marked as surviving the holder's process."""
    return bool(getattr(store, _DURABLE_LEASE_ATTR, False))


# --------------------------------------------------------------------------- #
# The chokepoint a module calls
# --------------------------------------------------------------------------- #


def _require_store() -> LeaseStore:
    """The active store, or a :class:`LeaseError` naming the wiring that is missing."""
    if _active_store is None:
        raise LeaseError(
            "no lease store is configured; pass create_app(lease_store=...) — e.g. "
            "terp-cap-leases' DatabaseLeaseStore, which keeps leases in the same "
            "database as the rows they protect. There is deliberately no in-process "
            "default: a per-process lease would let two workers hold one resource."
        )
    return _active_store


def acquire_lease(
    session: Session,
    resource: LeaseResource,
    *,
    holder: str,
    ttl_seconds: float,
) -> Lease | None:
    """Take *resource* for *holder* until ``ttl_seconds`` from now, or ``None`` if held.

    The primitive: ``None`` means somebody else holds it and their lease has not lapsed —
    a queue worker moves on to the next candidate rather than treating that as an error.
    Use :func:`hold_lease` when the caller needs *this* resource or nothing.
    """
    return _require_store().acquire(session, resource, holder=holder, ttl_seconds=ttl_seconds)


def hold_lease(
    session: Session,
    resource: LeaseResource,
    *,
    holder: str,
    ttl_seconds: float,
) -> LeaseGuard:
    """Take *resource* or raise :class:`LeaseHeldError`, returning a heartbeating guard.

    The mutex form — "at most one active run per pipeline" — and the ergonomic one: the
    returned :class:`LeaseGuard` carries the current lease, renews it from inside the work
    loop, and releases on the way out of its ``with`` block. A caller that would rather
    skip than fail uses :func:`acquire_lease` and checks for ``None``.
    """
    lease = acquire_lease(session, resource, holder=holder, ttl_seconds=ttl_seconds)
    if lease is None:
        raise LeaseHeldError()
    return LeaseGuard(session, lease, ttl_seconds=ttl_seconds)


def renew_lease(session: Session, lease: Lease, *, ttl_seconds: float) -> Lease | None:
    """Extend *lease*, or ``None`` when it was lost (expired and possibly re-granted)."""
    return _require_store().renew(session, lease, ttl_seconds=ttl_seconds)


def release_lease(session: Session, lease: Lease) -> bool:
    """Hand the resource back; ``False`` when *lease* no longer holds it."""
    return _require_store().release(session, lease)


def expired_leases(
    session: Session, *, kind: str | None = None, limit: int = 100
) -> tuple[Lease, ...]:
    """Up to *limit* still-held leases past their expiry — what a reaper must recover."""
    return _require_store().expired(session, kind=kind, limit=limit)


def forfeit_lease(session: Session, lease: Lease) -> bool:
    """Clear an expired *lease* once its reaper ran; ``False`` if already re-granted."""
    return _require_store().forfeit(session, lease)


def purge_free_leases(session: Session, *, idle_seconds: float) -> int:
    """Delete free lease records idle for *idle_seconds*; return how many went."""
    return _require_store().purge(session, idle_seconds=idle_seconds)


class LeaseGuard:
    """A held lease plus its heartbeat — what a leased unit of work carries around.

    Mutable on purpose: the lease itself is immutable, so a renewal produces a new value
    and *something* has to hold "the current one". This is that something, and it is what
    makes the seam safe to use inside a loop:

    * :meth:`heartbeat` is cheap to call per record — it writes only once the lease is
      past its half-life — and **raises** :class:`LeaseLostError` when the lease is gone,
      rather than returning a boolean a caller can forget to check. Losing a lease means a
      successor may already be doing this work, so stopping is the only safe answer.
    * :meth:`release` is idempotent, so a ``finally`` block can call it unconditionally.

    Used as a context manager it cannot leak a lease::

        with hold_lease(session, resource, holder=worker_id, ttl_seconds=60) as guard:
            for record in records:
                guard.heartbeat()
                ...
    """

    def __init__(self, session: Session, lease: Lease, *, ttl_seconds: float) -> None:
        self._session = session
        self._lease = lease
        self._ttl_seconds = ttl_seconds
        self._released = False

    @property
    def lease(self) -> Lease:
        """The current lease — a later ``expires_at`` after each effective heartbeat."""
        return self._lease

    @property
    def released(self) -> bool:
        """Whether this guard has already given the resource back."""
        return self._released

    def heartbeat(self) -> Lease:
        """Renew the lease if it is past its half-life; fail closed if it was lost.

        Returns the current lease either way, so a caller can log its expiry. Raises
        :class:`LeaseLostError` when the renewal was fenced out — the work must stop.
        """
        if self._released:
            raise LeaseLostError()
        store = _require_store()
        remaining = self._lease.remaining(store.clock()).total_seconds()
        if remaining > self._ttl_seconds * _RENEW_AFTER_FRACTION:
            return self._lease
        renewed = store.renew(self._session, self._lease, ttl_seconds=self._ttl_seconds)
        if renewed is None:
            self._released = True
            raise LeaseLostError()
        self._lease = renewed
        return renewed

    def release(self) -> bool:
        """Give the resource back; idempotent, so ``finally`` may call it unconditionally."""
        if self._released:
            return False
        self._released = True
        return _require_store().release(self._session, self._lease)

    def __enter__(self) -> LeaseGuard:
        return self

    def __exit__(self, *exc_info: object) -> None:
        """Release on the way out — including on an exception.

        An exception means the holder is alive and reporting, so the resource should go
        back immediately and let a retry through; only a *crash* leaves the lease to
        expire, which is exactly when the reaper is the right recovery.
        """
        self.release()


__all__ = [
    "LEASE_HOLDER_MAX",
    "LEASE_KEY_MAX",
    "LEASE_KIND_MAX",
    "InMemoryLeaseStore",
    "Lease",
    "LeaseError",
    "LeaseGuard",
    "LeaseHeldError",
    "LeaseLostError",
    "LeaseReaper",
    "LeaseResource",
    "LeaseStore",
    "acquire_lease",
    "active_lease_store",
    "configure_leases",
    "expired_leases",
    "forfeit_lease",
    "hold_lease",
    "is_durable_lease_store",
    "lease_reaper_for",
    "mark_durable_lease_store",
    "purge_free_leases",
    "register_lease_reaper",
    "registered_lease_reapers",
    "release_lease",
    "renew_lease",
    "reset_lease_reapers",
    "reset_leases_runtime",
]
