"""The durable schedule ledger: each schedule's last settled slot, in the app's own database.

A scheduler is a process, and a deploy stops it. A cron time that passes while it is down
leaves no trace in the scheduler (APScheduler and Celery beat keep their state in memory or
a file the next container does not have), so a restarted scheduler cannot know it missed a
tick, let alone apply the schedule's declared misfire policy to it. This ledger is that
memory (ADR 0191): :func:`terp.core.settle_schedule` reads the last slot of a schedule,
decides, and moves the record on with a compare-and-set.

It belongs to the outbox because a tick *is* an outbox row when the outbox is the job
queue: :func:`~terp.core.settle_schedule` opens one write unit, the enqueue appends the row
to it, the ledger stages its record in it, and one commit lands both. A crash between the two
cannot happen, so a tick is neither lost nor fired twice; and a second scheduler that settles
the same slot loses the compare-and-set and rolls its row back. Under a broker queue the job
is published before the record commits, so delivery is at least once, as it always is.

Wire it at the composition root, and promise it in production::

    create_app(..., job_queue=OutboxJobQueue(), schedule_ledger=DatabaseScheduleLedger(),
               require_durable_schedules=settings.is_production)
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from sqlmodel import Session

from terp.core import ScheduleLedger, ScheduleRecord, mark_durable_schedule_ledger

from terp.capabilities.outbox.models import ScheduleFire
from terp.capabilities.outbox.store import settle_slot


def _as_utc(moment: datetime) -> datetime:
    """A stored timestamp as aware UTC (SQLite hands back a naive one; it was written UTC)."""
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


class DatabaseScheduleLedger(ScheduleLedger):
    """A :class:`~terp.core.ScheduleLedger` over the ``outbox_schedule_fire`` table.

    Marked durable, so ``create_app(require_durable_schedules=True)`` accepts it. It reads and
    writes on the session :func:`~terp.core.settle_schedule` hands it; :meth:`settle` is one
    write unit holding the tick's outbox row and its record (:func:`settle_slot`).
    """

    def __init__(self) -> None:
        mark_durable_schedule_ledger(self)

    def last(self, session: Session, name: str) -> ScheduleRecord | None:
        row = session.get(ScheduleFire, name)
        if row is None:
            return None
        return ScheduleRecord(slot=_as_utc(row.slot), outcome=row.outcome, fires=row.fires)

    def settle(
        self,
        session: Session,
        name: str,
        *,
        expected: ScheduleRecord | None,
        slot: datetime,
        outcome: str,
        enqueue: Callable[[], str] | None,
    ) -> tuple[bool, str | None]:
        return settle_slot(
            session,
            name=name,
            expected_fires=None if expected is None else expected.fires,
            slot=slot,
            outcome=outcome,
            enqueue=enqueue,
        )


__all__ = ["DatabaseScheduleLedger"]
