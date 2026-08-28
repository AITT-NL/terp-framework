"""The outbox's raw persistence — the one module that writes the delivery table.

Three operations, deliberately isolated here so every governed ``# arch-allow-*``
opt-out lives in one place:

* :func:`append` stages a row on the **business write's own session**, riding the
  audited write unit so it commits atomically with the mutation that produced it (a
  nested enqueue defers to the outer ``BaseService`` commit; a standalone enqueue is
  its own durable unit). It cannot route through ``BaseService`` —
  :class:`~terp.capabilities.outbox.models.OutboxMessage` is not a ``BaseTable`` — so
  it appends directly, exactly like the durable audit sink at the base of the write
  stack.
* :func:`claim_due` leases a batch of due rows with a single atomic UPDATE (portable
  across SQLite and PostgreSQL; ``SKIP LOCKED`` is added on a backend that supports
  it), so N workers drain one outbox without double-dispatch.
* :func:`finalize` commits a worker's status transition (dispatched / rescheduled /
  dead-lettered) on the outbox's own table.
* :func:`backlog` reads what is waiting, and is the only one of the four that writes
  nothing. It exists because an outbox with no consumer is otherwise indistinguishable
  from an outbox with idle consumers: both are a table of ``pending`` rows. The lease
  reaper cannot tell them apart either, by construction — it scans LAPSED claims, and
  work nobody ever claimed has no claim to lapse. What distinguishes them is how long
  the oldest DUE row has been due, so that is the number this returns.

The worker drives :func:`claim_due` / :func:`finalize` on a **plain** session, but the
session is still a :class:`~terp.core._internal.session_guard.WriteGuardedSession`
(handed out by the same session factory as the request session), so both ride
:func:`~terp.core._internal.session_guard.enter_write_unit` too, exactly like
:func:`append` — the lease UPDATE and the status-transition commit are themselves
unaudited, infrastructure-only writes on the outbox's own table, not a business
mutation, but the guard cannot tell that from an ``# arch-allow-*`` comment alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, or_, update
from sqlmodel import Session, col, select

# The outbox is framework delivery infrastructure: its row must ride the audited write
# unit to commit atomically with the business write (the no-dual-write guarantee), a
# scope kept under _internal so an app module cannot open it to wave a write past the
# audit guard. The capability legitimately reaches it, like the audit sink reaches the
# base of the write stack.
from terp.core._internal.session_guard import enter_write_unit  # arch-allow-no-internal-imports: durable delivery infra must ride the audited write unit to append atomically with the business write; the scope primitive is _internal so app modules cannot open it

from terp.capabilities.outbox.models import (
    STATUS_DEAD_LETTERED,
    STATUS_PENDING,
    OutboxMessage,
)


@dataclass(frozen=True)
class OutboxBacklog:
    """What is waiting in the outbox, and how long the oldest ready item has waited.

    ``oldest_due_age_seconds`` is the field that answers "is anything draining this?",
    and it is the reason a plain count is not enough: a healthy busy queue and a queue
    whose worker died both show pending rows. A row that has been DUE for an hour, with
    no live claim on it, means no consumer is running — the one condition the outbox
    could not previously report about itself.

    ``pending`` counts everything undelivered, including rows deliberately scheduled for
    later or backing off between retries; ``due`` counts only what a worker could claim
    right now. Both age fields are ``None`` when nothing is due, which is the good case.
    """

    pending: int
    due: int
    dead_lettered: int
    oldest_due_at: datetime | None
    oldest_due_age_seconds: float | None

    def as_dict(self) -> dict[str, object]:
        """A JSON-safe rendering (the health detail and the CLI share it)."""
        return {
            "pending": self.pending,
            "due": self.due,
            "dead_lettered": self.dead_lettered,
            "oldest_due_at": (
                None if self.oldest_due_at is None else self.oldest_due_at.isoformat()
            ),
            "oldest_due_age_seconds": (
                None
                if self.oldest_due_age_seconds is None
                else round(self.oldest_due_age_seconds, 3)
            ),
        }


def append(session: Session, message: OutboxMessage) -> OutboxMessage:
    """Append *message* to the outbox inside the caller's audited write unit.

    Rides :func:`~terp.core._internal.session_guard.enter_write_unit` so the INSERT
    joins whatever transaction is open on *session*: enqueued from within a
    ``BaseService`` write (the common case), the row commits atomically with the
    business mutation and a rollback drops both; enqueued standalone, it is its own
    outermost, committed unit. Returns *message* (its id is assigned at construction).
    """
    message.assert_within_column_bounds()
    with enter_write_unit() as outermost:
        session.add(message)  # arch-allow-mutations-emit-audit: append-only delivery infra at the base of the write stack (like the audit sink); OutboxMessage is not a BaseTable, so it cannot route through BaseService
        if outermost:
            session.commit()  # arch-allow-mutations-emit-audit: a standalone enqueue is its own durable unit; a nested enqueue defers to the outer BaseService commit
    return message


def claim_due(
    session: Session,
    *,
    claim_id: str,
    now: datetime,
    lease_until: datetime,
    limit: int,
    skip_locked: bool = False,
) -> list[OutboxMessage]:
    """Atomically lease up to *limit* due, unlocked rows to *claim_id*; return them.

    A single UPDATE marks the due rows (``pending``, ``available_at`` reached, lease
    free or expired) with this worker's unique *claim_id* and *lease_until*, so two
    workers never grab the same row — portable across SQLite and PostgreSQL, with
    ``SELECT ... FOR UPDATE SKIP LOCKED`` added on a backend that supports it
    (*skip_locked*; SQLite silently ignores the clause, the atomic UPDATE still
    serialises writers). The follow-up SELECT returns exactly the rows this claim won
    (its *claim_id* is unique per cycle). A crashed worker's rows are reclaimed once
    ``lease_until`` passes (the ``locked_until < now`` branch) — at-least-once.
    """
    due = (
        select(OutboxMessage.id)
        .where(
            col(OutboxMessage.status) == STATUS_PENDING,
            col(OutboxMessage.available_at) <= now,
            or_(
                col(OutboxMessage.locked_until).is_(None),
                col(OutboxMessage.locked_until) < now,
            ),
        )
        .order_by(col(OutboxMessage.available_at), col(OutboxMessage.id))
        .limit(limit)
    )
    if skip_locked:
        due = due.with_for_update(skip_locked=True)
    with enter_write_unit() as outermost:
        session.execute(  # arch-allow-mutations-emit-audit: the atomic lease claim on the outbox's own table — a portable SKIP-LOCKED-style lock, not a business mutation
            update(OutboxMessage)
            .where(col(OutboxMessage.id).in_(due))
            .values(locked_by=claim_id, locked_until=lease_until)
        )
        if outermost:
            session.commit()  # arch-allow-mutations-emit-audit: commit the lease so concurrent workers observe it
    return list(
        session.exec(
            select(OutboxMessage)
            .where(col(OutboxMessage.locked_by) == claim_id)
            .order_by(col(OutboxMessage.available_at), col(OutboxMessage.id))
        ).all()
    )


def finalize(session: Session) -> None:
    """Commit a worker's in-place status transition on the outbox's own table."""
    with enter_write_unit():
        session.commit()  # arch-allow-mutations-emit-audit: persist the worker's status transition (dispatched / rescheduled / dead-lettered)


__all__ = ["append", "claim_due", "finalize"]


def backlog(session: Session, *, now: datetime | None = None) -> OutboxBacklog:
    """What is waiting in the outbox right now. Reads only; writes nothing.

    "Due" mirrors :func:`claim_due`'s own predicate exactly — pending, ``available_at``
    reached, and the lease free or expired — because the question being asked is "what
    could a worker take, and how long has it been sitting there". A measure that drifted
    from what the worker actually claims would report a backlog nobody can drain, or
    miss one nobody is draining.

    The age is computed in Python rather than in SQL so the answer is identical on
    SQLite and PostgreSQL. That matters more than the microsecond it costs: this number
    is the one an alert threshold gets written against.
    """
    moment = now or datetime.now(UTC)
    pending = session.exec(
        select(func.count()).where(col(OutboxMessage.status) == STATUS_PENDING)
    ).one()
    dead_lettered = session.exec(
        select(func.count()).where(col(OutboxMessage.status) == STATUS_DEAD_LETTERED)
    ).one()
    due_count, oldest_due = session.exec(
        select(func.count(), func.min(col(OutboxMessage.available_at))).where(
            col(OutboxMessage.status) == STATUS_PENDING,
            col(OutboxMessage.available_at) <= moment,
            or_(
                col(OutboxMessage.locked_until).is_(None),
                col(OutboxMessage.locked_until) < moment,
            ),
        )
    ).one()
    if oldest_due is not None and oldest_due.tzinfo is None:
        # SQLite hands back a naive value for a timezone-aware column, and the
        # subtraction below would raise on it. A health probe must never be the thing
        # that breaks; the column is written in UTC, so that is what it is.
        oldest_due = oldest_due.replace(tzinfo=UTC)
    return OutboxBacklog(
        pending=int(pending or 0),
        due=int(due_count or 0),
        dead_lettered=int(dead_lettered or 0),
        oldest_due_at=oldest_due,
        oldest_due_age_seconds=(
            None if oldest_due is None else max(0.0, (moment - oldest_due).total_seconds())
        ),
    )
