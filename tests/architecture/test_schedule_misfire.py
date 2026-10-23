"""A tick that fell due while no scheduler ran is settled by the schedule's policy (ADR 0191).

The kernel half of the scheduling amendment, engine-free: every
:class:`~terp.core.ScheduleDefinition` declares a :class:`~terp.core.Misfire` policy as a
required keyword, a :class:`~terp.core.ScheduleLedger` holds each schedule's last settled
slot, and :func:`~terp.core.settle_schedule` is the one decision both adapters make, at start
and on every cron time. The slot finder stands in for an adapter's cron, so each case below is
a statement about times alone: the last slot the ledger holds, the latest cron time since,
and now.

The adapters' restart proofs (two adapter instances sharing only a database) are in
``test_scheduler_adapters.py``; the durable ledger's own compare-and-set in ``test_outbox.py``.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlmodel import Field, Session, create_engine

from terp.core import (
    BaseSchema,
    BootError,
    InMemoryScheduleLedger,
    JobCatalog,
    JobDefinition,
    JobEnvelope,
    JobQueue,
    Misfire,
    ScheduleCatalog,
    ScheduleDefinition,
    ScheduleLedger,
    ScheduleRecord,
    create_app,
    is_durable_schedule_ledger,
    mark_durable_schedule_ledger,
    settle_schedule,
)
from terp.core.jobs import configure_jobs
from terp.core.runtime import capture_runtimes, restore_runtimes
from terp.core.scheduling import (
    BASELINE,
    FIRED,
    LATE,
    ON_TIME_SECONDS,
    SKIPPED,
    active_schedule_ledger,
    configure_schedules,
    reset_schedules_runtime,
)


class _Payload(BaseSchema):
    label: str | None = Field(default=None, max_length=50)


_JOB = JobDefinition(name="reports.build", payload_schema=_Payload, handler=lambda ctx, p: None)


def _schedule(misfire: Misfire, name: str = "reports.hourly") -> ScheduleDefinition:
    return ScheduleDefinition(name=name, job=_JOB, cron="0 * * * *", misfire=misfire)


def _at(hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2026, 10, 22, hour, minute, second, tzinfo=UTC)


def _hourly(after: datetime, until: datetime) -> datetime | None:
    """The cron ``0 * * * *`` in UTC, as an adapter's slot finder answers for it."""
    latest = until.replace(minute=0, second=0, microsecond=0)
    return latest if latest > after else None


class _Queue(JobQueue):
    def __init__(self) -> None:
        self.envelopes: list[JobEnvelope] = []

    def enqueue(self, session: Session, envelope: JobEnvelope) -> str:
        self.envelopes.append(envelope)
        return f"job-{len(self.envelopes)}"


@pytest.fixture
def queue() -> _Queue:
    captured = _Queue()
    configure_jobs(JobCatalog([_JOB]), queue=captured)
    return captured


@pytest.fixture
def session() -> Session:
    return Session(create_engine("sqlite://"))


def _settle(session, schedule, ledger, now):  # type: ignore[no-untyped-def]
    return settle_schedule(session, schedule, latest_slot=_hourly, now=now, ledger=ledger)


# --------------------------------------------------------------------------- #
# the declaration                                                               #
# --------------------------------------------------------------------------- #
def test_a_schedule_must_declare_its_misfire_policy() -> None:
    with pytest.raises(TypeError, match="misfire"):
        ScheduleDefinition(name="reports.hourly", job=_JOB, cron="0 * * * *")  # type: ignore[call-arg]
    with pytest.raises(TypeError, match="ADR 0191"):
        ScheduleDefinition(
            name="reports.hourly", job=_JOB, cron="0 * * * *", misfire="skip"  # type: ignore[arg-type]
        )
    assert _schedule(Misfire.RUN_ONCE).misfire is Misfire.RUN_ONCE
    assert {policy.value for policy in Misfire} == {"run-once", "skip"}


def test_on_time_is_a_minute() -> None:
    assert ON_TIME_SECONDS == 60.0


# --------------------------------------------------------------------------- #
# the ledger                                                                    #
# --------------------------------------------------------------------------- #
def test_the_in_memory_ledger_moves_only_from_the_record_it_was_shown(session: Session) -> None:
    ledger = InMemoryScheduleLedger()
    queued: list[str] = []

    def enqueue() -> str:
        queued.append("job")
        return f"job-{len(queued)}"

    def settle(expected, slot, outcome, runs=True):  # type: ignore[no-untyped-def]
        return ledger.settle(
            session, "reports.hourly", expected=expected, slot=slot, outcome=outcome,
            enqueue=enqueue if runs else None,
        )

    assert ledger.last(session, "reports.hourly") is None
    assert settle(None, _at(9), FIRED) == (True, "job-1")
    first = ledger.last(session, "reports.hourly")
    assert first == ScheduleRecord(slot=_at(9), outcome=FIRED, fires=1)
    assert settle(None, _at(10), FIRED) == (False, None), "a record that exists is not made again"
    assert settle(first, _at(10), SKIPPED, runs=False) == (True, None)
    assert settle(first, _at(11), FIRED) == (False, None), "moved since it was read"
    assert ledger.last(session, "reports.hourly") == ScheduleRecord(_at(10), SKIPPED, 2)
    assert queued == ["job"], "a lost compare-and-set enqueues nothing"


def test_only_a_marked_ledger_is_durable() -> None:
    ledger = InMemoryScheduleLedger()
    assert not is_durable_schedule_ledger(ledger) and not is_durable_schedule_ledger(None)
    assert mark_durable_schedule_ledger(ledger) is ledger
    assert is_durable_schedule_ledger(ledger)


def test_the_ledger_is_part_of_the_schedules_runtime() -> None:
    reset_schedules_runtime()
    default = active_schedule_ledger()
    assert isinstance(default, InMemoryScheduleLedger)
    chosen = InMemoryScheduleLedger()
    snapshot = capture_runtimes()
    configure_schedules(ScheduleCatalog(), ledger=chosen)
    assert active_schedule_ledger() is chosen
    restore_runtimes(snapshot)
    assert active_schedule_ledger() is default
    configure_schedules(ScheduleCatalog())
    assert active_schedule_ledger() is not default, "no ledger given, a fresh one"
    reset_schedules_runtime()
    assert isinstance(active_schedule_ledger(), InMemoryScheduleLedger)


def test_require_durable_schedules_refuses_a_ledger_that_forgets() -> None:
    with pytest.raises(BootError, match="require_durable_schedules=True"):
        create_app([], require_durable_schedules=True)
    with pytest.raises(BootError, match="DatabaseScheduleLedger"):
        create_app([], schedule_ledger=InMemoryScheduleLedger(), require_durable_schedules=True)
    durable = mark_durable_schedule_ledger(InMemoryScheduleLedger())
    create_app([], schedule_ledger=durable, require_durable_schedules=True)
    assert active_schedule_ledger() is durable


# --------------------------------------------------------------------------- #
# the decision                                                                  #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("misfire", list(Misfire))
def test_a_first_start_between_cron_times_records_a_baseline_and_runs_nothing(
    misfire: Misfire, queue: _Queue, session: Session
) -> None:
    ledger = InMemoryScheduleLedger()
    settled = _settle(session, _schedule(misfire), ledger, _at(9, 20))
    assert (settled.outcome, settled.slot, settled.job_id) == (BASELINE, _at(9, 20), None)
    assert queue.envelopes == []
    assert ledger.last(session, "reports.hourly") == ScheduleRecord(_at(9, 20), BASELINE, 1)
    # Nothing owed until the next cron time, which then runs on time.
    assert _settle(session, _schedule(misfire), ledger, _at(9, 40)).outcome is None
    assert _settle(session, _schedule(misfire), ledger, _at(10, 0, 3)).outcome == FIRED


@pytest.mark.parametrize("misfire", list(Misfire))
def test_a_cron_time_settled_within_the_minute_runs_whatever_the_policy(
    misfire: Misfire, queue: _Queue, session: Session
) -> None:
    ledger = InMemoryScheduleLedger()
    settled = _settle(session, _schedule(misfire), ledger, _at(9, 0, 59))
    assert (settled.outcome, settled.slot, settled.job_id) == (FIRED, _at(9), "job-1")
    assert [envelope.name for envelope in queue.envelopes] == ["reports.build"]
    again = _settle(session, _schedule(misfire), ledger, _at(9, 0, 59))
    assert again.outcome is None and len(queue.envelopes) == 1, "a slot runs once"


def test_run_once_runs_the_missed_tick_once_late_and_folds_the_gap(
    queue: _Queue, session: Session, caplog: pytest.LogCaptureFixture
) -> None:
    ledger = InMemoryScheduleLedger()
    _settle(session, _schedule(Misfire.RUN_ONCE), ledger, _at(9, 0, 5))
    with caplog.at_level(logging.WARNING, logger="terp.core.scheduling"):
        settled = _settle(session, _schedule(Misfire.RUN_ONCE), ledger, _at(12, 1, 1))
    assert (settled.outcome, settled.slot, settled.job_id) == (LATE, _at(12), "job-2")
    assert len(queue.envelopes) == 2, "ten, eleven and twelve are one run"
    assert "ran late, once (misfire policy run-once)" in caplog.text
    assert ledger.last(session, "reports.hourly") == ScheduleRecord(_at(12), LATE, 2)


def test_skip_records_the_missed_tick_and_runs_nothing(
    queue: _Queue, session: Session, caplog: pytest.LogCaptureFixture
) -> None:
    ledger = InMemoryScheduleLedger()
    _settle(session, _schedule(Misfire.SKIP), ledger, _at(9, 0, 5))
    with caplog.at_level(logging.WARNING, logger="terp.core.scheduling"):
        settled = _settle(session, _schedule(Misfire.SKIP), ledger, _at(11, 30))
    assert (settled.outcome, settled.slot, settled.job_id) == (SKIPPED, _at(11), None)
    assert len(queue.envelopes) == 1
    assert "was skipped (misfire policy skip)" in caplog.text
    assert _settle(session, _schedule(Misfire.SKIP), ledger, _at(12, 0, 1)).outcome == FIRED


@pytest.mark.parametrize(
    ("now", "outcome"), [(_at(9, 1, 0), FIRED), (_at(9, 1, 1), SKIPPED)], ids=["60s", "61s"]
)
def test_a_slot_more_than_a_minute_old_is_a_misfire(
    now: datetime, outcome: str, queue: _Queue, session: Session
) -> None:
    ledger = InMemoryScheduleLedger()
    ledger.settle(
        session, "reports.hourly", expected=None, slot=_at(8), outcome=FIRED, enqueue=None
    )
    assert _settle(session, _schedule(Misfire.SKIP), ledger, now).outcome == outcome


class _Lost(ScheduleLedger):
    """A ledger another scheduler always moves first."""

    def last(self, session: Session, name: str) -> ScheduleRecord | None:
        return ScheduleRecord(_at(8), FIRED, 1)

    def settle(self, session, name, *, expected, slot, outcome, enqueue):  # type: ignore[no-untyped-def]
        # A broker-style queue has published before the record could be compared.
        return False, enqueue() if enqueue is not None else None


def test_a_slot_another_scheduler_settled_first_is_not_overwritten(
    queue: _Queue, session: Session, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="terp.core.scheduling"):
        fired = _settle(session, _schedule(Misfire.SKIP), _Lost(), _at(9, 0, 2))
        skipped = _settle(session, _schedule(Misfire.SKIP), _Lost(), _at(9, 30))
    assert fired.outcome is None and skipped.outcome is None
    assert "settled by another scheduler first" in caplog.text
    assert "had already left on a queue outside the transaction" in caplog.text
    assert len(queue.envelopes) == 1, "only the broker-style queue is beyond the rollback"


def test_settle_reads_the_clock_and_the_active_ledger_by_default(
    queue: _Queue, session: Session
) -> None:
    ledger = InMemoryScheduleLedger()
    configure_schedules(ScheduleCatalog([_schedule(Misfire.SKIP)]), ledger=ledger)
    before = datetime.now(UTC)
    settled = settle_schedule(session, _schedule(Misfire.SKIP), latest_slot=lambda a, u: None)
    assert settled.outcome == BASELINE and before <= settled.slot <= datetime.now(UTC)
    assert ledger.last(session, "reports.hourly") is not None


def test_times_are_compared_in_utc_whatever_zone_a_finder_answers_in(
    queue: _Queue, session: Session
) -> None:
    plus_two = timezone(timedelta(hours=2))
    naive_nine = datetime(2026, 10, 22, 9, 0)
    settled = settle_schedule(
        session,
        _schedule(Misfire.SKIP),
        latest_slot=lambda after, until: naive_nine,
        now=datetime(2026, 10, 22, 11, 0, 30, tzinfo=plus_two),
        ledger=InMemoryScheduleLedger(),
    )
    assert (settled.outcome, settled.slot) == (FIRED, _at(9)), "11:00:30+02:00 is 09:00:30Z"
