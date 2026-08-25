"""``DatabaseLeaseStore`` — the durable half of the lease seam, in the app's own database.

The one place leases can be correct is the database that holds the rows they protect. That
is not an implementation preference, it is the requirement: taking a lease has to commit or
roll back **with** the state change it guards, or a crash between the two re-creates the
orphaned ``claimed`` row the lease exists to prevent. So every operation here writes on the
**caller's** session — a claim taken inside a ``BaseService`` write joins that transaction; a
standalone claim is its own committed unit — exactly like the durable outbox's ``append``.

Four statements carry the whole contract, and each is a *single* atomic conditional
statement rather than a read-then-write, so correctness never depends on isolation level:

* **acquire** — ``UPDATE … SET holder = :me, epoch = :epoch + 1 WHERE resource = … AND
  epoch = :epoch AND (holder IS NULL OR expires_at <= :now)``. Two workers racing for a free
  resource read the same epoch and both try; the database applies one, the loser matches
  zero rows and is told the resource is taken. A first-ever acquire has no row to update, so
  it inserts inside a SAVEPOINT — the unique constraint on
  ``(resource_kind, resource_key)`` makes a concurrent insert lose cleanly, and the loser
  falls back to the conditional UPDATE.
* **renew** — the same fence plus ``AND expires_at > :now``, so a lapsed lease is never
  resurrected: by then the resource may belong to a successor.
* **release** — the fence *without* the expiry condition, because finishing late while
  nobody took over should still hand the resource back cleanly; if a successor did take it,
  the epoch has moved and the release matches nothing.
* **forfeit** — the fence plus ``AND expires_at <= :now``: the reaper's tool, which by
  construction cannot steal a live lease.

Two details keep the store honest about *other people's* transactions. Every read here
selects **columns, never the ORM entity**, so a lease row never enters the caller's identity
map — otherwise a conditional UPDATE would leave a stale copy behind for the next read to
believe, and the alternative (expiring the session) would throw away the pending business
write this claim is supposed to be atomic with. And every DML statement runs with
``synchronize_session=False`` for the same reason: the caller's session is theirs, and lease
bookkeeping has no business rewriting what is loaded in it.

``SELECT … FOR UPDATE SKIP LOCKED`` is added to the reaper's scan when the deployment says
its backend supports it (``skip_locked=True``, the way ``terp jobs worker`` decides it for the
outbox — the capability does not reach for the engine to find out). Leaving it off is a
contention choice, never a correctness one: the scan is bounded and every forfeit is fenced,
so two overlapping reapers recover disjoint sets either way.

Nothing here is audited: a lease write is infrastructure on the lease's own table — the
*domain* transition it accompanies is audited by the domain's own service, and auditing a
heartbeat every few seconds per resource would bury that trail rather than enrich it.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import ColumnElement, Executable, Row, delete, or_, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from terp.core import Lease, LeaseResource, LeaseStore, mark_durable_lease_store

# Lease bookkeeping must ride the caller's audited write unit so a claim commits atomically
# with the state change it protects (the no-orphan guarantee). The scope primitive is kept
# _internal so an app module cannot open it to wave a write past the audit guard; delivery
# and lease infrastructure legitimately reach it, like the audit sink at the base of the
# write stack.
from terp.core._internal.session_guard import enter_write_unit  # arch-allow-no-internal-imports: lease infra must ride the audited write unit to claim atomically with the business write; the scope primitive is _internal so app modules cannot open it

from terp.capabilities.leases.models import ResourceLease

# Lease DML must not rewrite what the caller has loaded: the ORM's default "evaluate then
# synchronise" pass would walk the caller's identity map (and, on a timezone-naive backend,
# compare a naive stored expiry against the seam's aware clock while doing it).
_NO_SYNC = {"synchronize_session": False}


def _utc_now() -> datetime:
    """UTC ``now`` provider — the default clock, injectable for tests."""
    return datetime.now(UTC)


class DatabaseLeaseStore(LeaseStore):
    """A :class:`~terp.core.LeaseStore` backed by the ``resource_lease`` table.

    Marked durable (:func:`~terp.core.mark_durable_lease_store`), so
    ``create_app(require_durable_leases=True)`` accepts it where the in-memory store is
    refused: these leases outlive the worker that took them, which is the only reason a
    crashed holder's claim can be reaped at all. The clock is injectable so a test can
    expire a lease without sleeping.

    *skip_locked* adds ``FOR UPDATE SKIP LOCKED`` to the reaper's scan on a backend that
    supports it (PostgreSQL, MySQL, Oracle); it defaults off so the portable path is the
    default, and ``terp leases reap`` sets it from the live engine exactly as
    ``terp jobs worker`` does for the outbox. The capability deliberately does not reach for
    the connection itself to find out.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] = _utc_now,
        skip_locked: bool = False,
    ) -> None:
        self.clock = clock
        self._skip_locked = skip_locked
        mark_durable_lease_store(self)

    # ----------------------------------------------------------------- acquire
    def acquire(
        self, session: Session, resource: LeaseResource, *, holder: str, ttl_seconds: float
    ) -> Lease | None:
        _validate_holder(holder)
        _validate_ttl(ttl_seconds)
        now = self.clock()
        expires_at = now + timedelta(seconds=ttl_seconds)
        current = self._find(session, resource)
        if current is None:
            inserted = self._insert(
                session, resource, holder=holder, expires_at=expires_at, now=now
            )
            if inserted is not None:
                return inserted
            # Lost the insert race: the winner's record exists now, so fall through to the
            # conditional UPDATE, which finds it held and refuses.
            current = self._find(session, resource)
            if current is None:  # pragma: no cover - the winner's row is committed by now
                return None
        expiry = _aware(current.expires_at)
        if current.holder is not None and expiry is not None and expiry > now:
            return None
        epoch = current.epoch
        claimed = self._apply(
            session,
            update(ResourceLease)
            .where(
                col(ResourceLease.resource_kind) == resource.kind,
                col(ResourceLease.resource_key) == resource.key,
                col(ResourceLease.epoch) == epoch,
                _free_or_expired(now),
            )
            .values(
                holder=holder,
                epoch=epoch + 1,
                expires_at=expires_at,
                acquired_at=now,
                touched_at=now,
            ),
        )
        if claimed != 1:
            return None
        return Lease(resource=resource, holder=holder, epoch=epoch + 1, expires_at=expires_at)

    # ------------------------------------------------------------------- renew
    def renew(self, session: Session, lease: Lease, *, ttl_seconds: float) -> Lease | None:
        _validate_ttl(ttl_seconds)
        now = self.clock()
        expires_at = now + timedelta(seconds=ttl_seconds)
        renewed = self._apply(
            session,
            update(ResourceLease)
            .where(*_fence(lease), col(ResourceLease.expires_at) > now)
            .values(expires_at=expires_at, touched_at=now),
        )
        if renewed != 1:
            return None
        return Lease(
            resource=lease.resource,
            holder=lease.holder,
            epoch=lease.epoch,
            expires_at=expires_at,
        )

    # ----------------------------------------------------------------- release
    def release(self, session: Session, lease: Lease) -> bool:
        return (
            self._apply(
                session,
                update(ResourceLease)
                .where(*_fence(lease))
                .values(holder=None, expires_at=None, touched_at=self.clock()),
            )
            == 1
        )

    # ---------------------------------------------------------------- read-back
    def lease_for(
        self, session: Session, resource: LeaseResource, *, holder: str | None = None
    ) -> Lease | None:
        query = select(
            ResourceLease.resource_kind,
            ResourceLease.resource_key,
            ResourceLease.holder,
            ResourceLease.epoch,
            ResourceLease.expires_at,
        ).where(
            col(ResourceLease.resource_kind) == resource.kind,
            col(ResourceLease.resource_key) == resource.key,
            col(ResourceLease.holder).is_not(None),
        )
        if holder is not None:
            query = query.where(col(ResourceLease.holder) == holder)
        row = session.exec(query).first()
        return _as_lease(row) if row is not None else None

    # ----------------------------------------------------------------- expired
    def expired(
        self, session: Session, *, kind: str | None = None, limit: int = 100
    ) -> tuple[Lease, ...]:
        _validate_limit(limit)
        now = self.clock()
        query = (
            select(
                ResourceLease.resource_kind,
                ResourceLease.resource_key,
                ResourceLease.holder,
                ResourceLease.epoch,
                ResourceLease.expires_at,
            )
            .where(
                col(ResourceLease.holder).is_not(None),
                col(ResourceLease.expires_at) <= now,
            )
            .order_by(col(ResourceLease.expires_at), col(ResourceLease.id))
            .limit(limit)
        )
        if kind is not None:
            query = query.where(col(ResourceLease.resource_kind) == kind)
        if self._skip_locked:
            query = query.with_for_update(skip_locked=True)
        return tuple(_as_lease(row) for row in session.exec(query).all())

    # ----------------------------------------------------------------- forfeit
    def forfeit(self, session: Session, lease: Lease) -> bool:
        now = self.clock()
        return (
            self._apply(
                session,
                update(ResourceLease)
                .where(*_fence(lease), col(ResourceLease.expires_at) <= now)
                .values(holder=None, expires_at=None, touched_at=now),
            )
            == 1
        )

    # ------------------------------------------------------------------- purge
    def purge(self, session: Session, *, idle_seconds: float) -> int:
        _validate_ttl(idle_seconds)
        cutoff = self.clock() - timedelta(seconds=idle_seconds)
        return self._apply(
            session,
            delete(ResourceLease).where(
                col(ResourceLease.holder).is_(None),
                col(ResourceLease.touched_at) < cutoff,
            ),
        )

    # ----------------------------------------------------------------- helpers
    @staticmethod
    def _find(session: Session, resource: LeaseResource) -> Row | None:
        """*resource*'s current custody (columns only), or ``None`` before its first acquire.

        Columns rather than the ORM entity on purpose: a lease row that entered the
        caller's identity map would be left stale by the conditional UPDATE that follows,
        and the next read in the same session would believe the stale copy.
        """
        return session.exec(  # type: ignore[return-value]
            select(
                ResourceLease.epoch,
                ResourceLease.holder,
                ResourceLease.expires_at,
            ).where(
                col(ResourceLease.resource_kind) == resource.kind,
                col(ResourceLease.resource_key) == resource.key,
            )
        ).first()

    @staticmethod
    def _apply(session: Session, statement: Executable) -> int:
        """Run one DML statement on the caller's write unit; return the rows it matched.

        The single DML chokepoint for the lease table, so the whole store's opt-out from the
        audited-write rule is these two lines rather than one per operation.
        """
        with enter_write_unit() as outermost:
            result = session.execute(statement, execution_options=_NO_SYNC)  # arch-allow-mutations-emit-audit: the fenced lease statement on the lease capability's own table — custody bookkeeping, not a business mutation (see module docstring)
            if outermost:
                session.commit()  # arch-allow-mutations-emit-audit: commit the lease so concurrent workers observe it; a nested claim defers to the caller's BaseService commit
        return int(result.rowcount)

    @staticmethod
    def _insert(
        session: Session,
        resource: LeaseResource,
        *,
        holder: str,
        expires_at: datetime,
        now: datetime,
    ) -> Lease | None:
        """Create the record for a never-before-leased *resource*, or ``None`` if raced.

        The INSERT runs inside a SAVEPOINT so a concurrent creator's unique-constraint
        violation rolls back only this statement — the caller's own transaction (which may
        already hold the business write this claim is atomic with) survives, and the loser
        retries as a conditional UPDATE.
        """
        row = ResourceLease(
            resource_kind=resource.kind,
            resource_key=resource.key,
            holder=holder,
            epoch=1,
            expires_at=expires_at,
            acquired_at=now,
            touched_at=now,
            created_at=now,
        )
        with enter_write_unit() as outermost:
            try:
                with session.begin_nested():
                    session.add(row)  # arch-allow-mutations-emit-audit: first acquire of a resource creates its lease record — infra on the lease capability's own table, guarded by a SAVEPOINT so a raced insert cannot poison the caller's transaction
            except IntegrityError:
                return None
            if outermost:
                session.commit()  # arch-allow-mutations-emit-audit: commit the new lease so concurrent workers observe it
        return Lease(resource=resource, holder=holder, epoch=1, expires_at=expires_at)


def _fence(lease: Lease) -> tuple[ColumnElement[bool], ...]:
    """The ``WHERE`` clause identifying *exactly* the grant *lease* records.

    Resource plus ``(holder, epoch)``. A superseded holder's statement matches zero rows,
    which is the whole fencing guarantee — expiry alone would let a paused worker come back
    and write over its successor.
    """
    return (
        col(ResourceLease.resource_kind) == lease.resource.kind,
        col(ResourceLease.resource_key) == lease.resource.key,
        col(ResourceLease.holder) == lease.holder,
        col(ResourceLease.epoch) == lease.epoch,
    )


def _free_or_expired(now: datetime) -> ColumnElement[bool]:
    """Matches a record nobody holds, or one whose lease has lapsed by *now*."""
    return or_(
        col(ResourceLease.holder).is_(None),
        col(ResourceLease.expires_at).is_(None),
        col(ResourceLease.expires_at) <= now,
    )


def _as_lease(row: Row) -> Lease:
    """Read one held lease record back as the seam's immutable :class:`~terp.core.Lease`."""
    return Lease(
        resource=LeaseResource(kind=row.resource_kind, key=row.resource_key),
        holder=str(row.holder),
        epoch=row.epoch,
        expires_at=_as_utc(row.expires_at),
    )


def _aware(value: datetime | None) -> datetime | None:
    """Re-attach UTC to a timestamp a backend handed back naive (SQLite does).

    Every stored expiry is written from the seam's UTC clock, but SQLite has nowhere to keep
    the offset and returns the value naive — which raises the moment it is compared with an
    aware ``now``, and that comparison is what every expiry check is. Normalising on the way
    out keeps the store's behaviour identical on both backends.
    """
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _as_utc(value: datetime | None) -> datetime:
    """:func:`_aware` for a column the query already constrained to be non-null."""
    expiry = _aware(value)
    if expiry is None:  # pragma: no cover - only held rows (expires_at NOT NULL) are read
        raise ValueError("a held lease record must carry an expiry")
    return expiry


def _validate_holder(holder: str) -> None:
    """Refuse an empty holder id before it reaches the column."""
    if not holder or not holder.strip():
        raise ValueError("a lease holder must be a non-empty string")


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


__all__ = ["DatabaseLeaseStore"]
