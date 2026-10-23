"""The schedule ledger: each schedule's last settled slot, the memory a scheduler lacks (ADR 0191).

A scheduler is a process, and a deploy, a crash or a host restart stops it. A cron time that
passes while no scheduler runs leaves no trace in the engine, so without a record kept
somewhere else it cannot be told from one that never existed, and no misfire policy can be
applied to it. A :class:`ScheduleLedger` is that record: for every schedule, the last cron
time a scheduler settled (fired, ran late, skipped) or the moment it first saw the schedule.

:func:`terp.core.settle_schedule` reads :meth:`ScheduleLedger.last`, decides, and hands the
decision to :meth:`ScheduleLedger.settle`, which enqueues the tick's job (when the decision
runs it) and moves the record on by compare-and-set, as one unit where the ledger can make it
one. The kernel ships :class:`InMemoryScheduleLedger`, which forgets on restart; the durable
one is the outbox capability's ``DatabaseScheduleLedger``, which records the slot in the same
transaction as the outbox row the tick enqueued, and is marked with
:func:`mark_durable_schedule_ledger` so ``create_app(require_durable_schedules=True)`` can
refuse anything else.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from threading import Lock
from typing import Final

from sqlmodel import Session

#: What a ledger records about the slot it settled.
FIRED: Final[str] = "fired"
LATE: Final[str] = "late"
SKIPPED: Final[str] = "skipped"
#: A schedule's first record, at the moment a ledger first saw it, with nothing owed before
#: it: nothing is known about the time before the ledger held the schedule.
BASELINE: Final[str] = "baseline"


@dataclass(frozen=True)
class ScheduleRecord:
    """What a :class:`ScheduleLedger` holds for one schedule: its last settled slot.

    *slot* is the cron time settled last, aware and in UTC; *outcome* what became of it
    (:data:`FIRED`, :data:`LATE`, :data:`SKIPPED` or :data:`BASELINE`); *fires* how many
    times the record has moved, the token :meth:`ScheduleLedger.settle` compares and sets.
    """

    slot: datetime
    outcome: str
    fires: int


class ScheduleLedger(ABC):
    """The record of each schedule's last settled slot (ADR 0191)."""

    @abstractmethod
    def last(self, session: Session, name: str) -> ScheduleRecord | None:
        """The record of schedule *name*, or ``None`` when the ledger has never held it."""

    @abstractmethod
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
        """Settle *slot* for *name*: enqueue when asked, and move the record from *expected*.

        Returns ``(moved, job_id)``. *enqueue* (``None`` when the outcome runs nothing)
        enqueues the tick's job and returns its id. ``moved`` is ``False`` when the record is
        no longer *expected*: another scheduler settled the slot first, and whatever this
        call staged must not survive it. A ledger in the app's database does both on
        *session*, in one write unit it commits, so the job and the record land together or
        not at all.
        """


class InMemoryScheduleLedger(ScheduleLedger):
    """The default ledger: per process, and gone with the process.

    A scheduler on it settles ticks exactly as on a durable one while it runs, and starts
    every life with nothing recorded: each schedule's first record is a baseline, and a tick
    that fell due while the process was down is never seen. Production wires the outbox
    capability's ``DatabaseScheduleLedger`` and can promise it with
    ``create_app(require_durable_schedules=True)``.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._records: dict[str, ScheduleRecord] = {}

    def last(self, session: Session, name: str) -> ScheduleRecord | None:
        with self._lock:
            return self._records.get(name)

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
        with self._lock:
            if self._records.get(name) != expected:
                return False, None
            job_id = enqueue() if enqueue is not None else None
            fires = 1 if expected is None else expected.fires + 1
            self._records[name] = ScheduleRecord(slot=slot, outcome=outcome, fires=fires)
            return True, job_id


# A marker stamped on a ledger that outlives its process (the outbox capability's
# DatabaseScheduleLedger), so ``create_app(require_durable_schedules=True)`` can fail closed
# when the per-process default is left in place. Mirrors the durable job queue and lease
# store markers: the backend stamps it, the boot guard checks it, neither imports the other.
_DURABLE_LEDGER_ATTR = "__terp_durable_schedule_ledger__"


def mark_durable_schedule_ledger(ledger: ScheduleLedger) -> ScheduleLedger:
    """Mark *ledger* as durable (its records survive a scheduler restart), and return it."""
    setattr(ledger, _DURABLE_LEDGER_ATTR, True)
    return ledger


def is_durable_schedule_ledger(ledger: ScheduleLedger | None) -> bool:
    """Return whether *ledger* is marked durable."""
    return bool(getattr(ledger, _DURABLE_LEDGER_ATTR, False))


__all__ = [
    "BASELINE",
    "FIRED",
    "LATE",
    "SKIPPED",
    "InMemoryScheduleLedger",
    "ScheduleLedger",
    "ScheduleRecord",
    "is_durable_schedule_ledger",
    "mark_durable_schedule_ledger",
]
