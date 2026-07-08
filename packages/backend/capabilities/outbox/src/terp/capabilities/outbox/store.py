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

The worker drives :func:`claim_due` / :func:`finalize` on a **plain** session — the
outbox is infrastructure managing its own table, not an audited business mutation —
so it never needs the write-guard scope :func:`append` opens for the request session.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_, update
from sqlmodel import Session, col, select

# The outbox is framework delivery infrastructure: its row must ride the audited write
# unit to commit atomically with the business write (the no-dual-write guarantee), a
# scope kept under _internal so an app module cannot open it to wave a write past the
# audit guard. The capability legitimately reaches it, like the audit sink reaches the
# base of the write stack.
from terp.core._internal.session_guard import enter_write_unit  # arch-allow-no-internal-imports: durable delivery infra must ride the audited write unit to append atomically with the business write; the scope primitive is _internal so app modules cannot open it

from terp.capabilities.outbox.models import STATUS_PENDING, OutboxMessage


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
    session.execute(  # arch-allow-mutations-emit-audit: the atomic lease claim on the outbox's own table — a portable SKIP-LOCKED-style lock, not a business mutation
        update(OutboxMessage)
        .where(col(OutboxMessage.id).in_(due))
        .values(locked_by=claim_id, locked_until=lease_until)
    )
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
    session.commit()  # arch-allow-mutations-emit-audit: persist the worker's status transition (dispatched / rescheduled / dead-lettered)


__all__ = ["append", "claim_due", "finalize"]
