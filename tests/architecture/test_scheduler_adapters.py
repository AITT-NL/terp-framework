"""Capability gate for the scheduler engine adapters (ADR 0048): APScheduler + Celery beat.

Both adapters build on the core scheduler seam (ADR 0047) and fire a
:class:`~terp.core.ScheduleDefinition` on its cron by **enqueuing its job through the typed
chokepoint** (:func:`~terp.core.trigger_schedule`) — so the SAME schedule fires identically
whichever engine is wired (the design's §11). These suites run the adapters broker-free (a fake
APScheduler that captures the registered job; a real Celery app whose registered tick task is
invoked directly), proving the tick reaches the active :class:`~terp.core.JobQueue`. The
adapters wrap a heavy engine, so they live in their own suite and are omitted from the core
``--cov=terp`` gate (the design's §16).

ADR 0191: each tick settles through :func:`~terp.core.settle_schedule` and the active
:class:`~terp.core.ScheduleLedger`, so a scheduler restarted across a cron time applies the
schedule's misfire policy. Proven here with each adapter over the outbox's
``DatabaseScheduleLedger`` and ``OutboxJobQueue`` on one SQLite file: two adapter instances
share nothing but that database, which is all a restarted scheduler process shares with the
one before it.
"""

from __future__ import annotations

import pathlib
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from celery import Celery
from celery.schedules import crontab
from sqlmodel import Field, Session, SQLModel, create_engine, select

from terp.core import (
    BaseSchema,
    JobCatalog,
    JobDefinition,
    JobEnvelope,
    JobQueue,
    Misfire,
    ScheduleCatalog,
    ScheduleDefinition,
)
from terp.core.jobs import configure_jobs

from terp.capabilities.outbox import (
    DatabaseScheduleLedger,
    OutboxJobQueue,
    OutboxMessage,
    ScheduleFire,
)
from terp.capabilities.scheduler_apscheduler import ApschedulerScheduler
from terp.capabilities.scheduler_celery_beat import CeleryBeatScheduler
from terp.capabilities.scheduler_celery_beat.scheduler import _to_crontab


class _Payload(BaseSchema):
    label: str | None = Field(default=None, max_length=50)


def _job() -> JobDefinition:
    return JobDefinition(
        name="sync.customers.pull",
        payload_schema=_Payload,
        handler=lambda ctx, payload: None,
    )


def _schedule(
    job: JobDefinition,
    *,
    name: str = "sync.customers.nightly",
    cron: str = "0 2 * * *",
    misfire: Misfire = Misfire.SKIP,
) -> ScheduleDefinition:
    return ScheduleDefinition(
        name=name,
        job=job,
        cron=cron,
        payload_factory=lambda: _Payload(label="tick"),
        misfire=misfire,
    )


class _CapturingQueue(JobQueue):
    def __init__(self) -> None:
        self.envelopes: list[JobEnvelope] = []

    def enqueue(self, session: Session, envelope: JobEnvelope) -> str:
        self.envelopes.append(envelope)
        return "captured"


@pytest.fixture
def session_factory() -> Iterator:
    engine = create_engine("sqlite://")
    yield lambda: Session(engine)
    engine.dispose()


def _at(hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2026, 10, 22, hour, minute, second, tzinfo=UTC)


class _Clock:
    """A clock a test moves by hand."""

    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def outbox_db(tmp_path: pathlib.Path) -> Iterator:
    """A file database with the outbox's tables: what a restarted scheduler shares."""
    engine = create_engine(f"sqlite:///{tmp_path / 'scheduler.db'}")
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


def _hourly(job: JobDefinition) -> tuple[ScheduleDefinition, ScheduleDefinition]:
    return (
        _schedule(job, name="reports.hourly", cron="0 * * * *", misfire=Misfire.RUN_ONCE),
        _schedule(job, name="reminders.hourly", cron="0 * * * *", misfire=Misfire.SKIP),
    )


def _queued(engine) -> int:  # type: ignore[no-untyped-def]
    with Session(engine) as session:
        return len(session.exec(select(OutboxMessage)).all())


def _records(engine) -> dict[str, tuple[datetime, str, int]]:  # type: ignore[no-untyped-def]
    with Session(engine) as session:
        return {
            row.name: (row.slot.replace(tzinfo=UTC), row.outcome, row.fires)
            for row in session.exec(select(ScheduleFire)).all()
        }


def _outcomes(engine) -> dict[str, str]:  # type: ignore[no-untyped-def]
    return {name: outcome for name, (_slot, outcome, _fires) in _records(engine).items()}


# --------------------------------------------------------------------------- #
# APScheduler adapter
# --------------------------------------------------------------------------- #
class _FakeAps:
    """A stand-in APScheduler that records add_job / start / shutdown (no real threads)."""

    def __init__(self) -> None:
        self.jobs: list[dict] = []
        self.started = False
        self.shut = False

    def add_job(self, func, *, trigger, id, name, replace_existing, **options) -> None:  # type: ignore[no-untyped-def]
        self.jobs.append(
            {"func": func, "trigger": trigger, "id": id, "name": name, "options": options}
        )

    def start(self) -> None:
        self.started = True

    def shutdown(self, wait: bool = True) -> None:
        self.shut = True


def _aps(engine, clock: _Clock, fake: _FakeAps | None = None) -> ApschedulerScheduler:  # type: ignore[no-untyped-def]
    """An APScheduler adapter over *engine* with its own ledger object: a fresh process."""
    return ApschedulerScheduler(
        lambda: Session(engine),
        scheduler=fake if fake is not None else _FakeAps(),
        ledger=DatabaseScheduleLedger(),
        timezone=UTC,
        clock=clock,
    )


def test_apscheduler_registers_a_cron_job_whose_tick_enqueues(session_factory) -> None:
    job = _job()
    queue = _CapturingQueue()
    configure_jobs(JobCatalog([job]), queue=queue)
    fake = _FakeAps()
    clock = _Clock(_at(2, 0, 5))
    scheduler = ApschedulerScheduler(session_factory, scheduler=fake, timezone=UTC, clock=clock)
    scheduler.register_all(ScheduleCatalog([_schedule(job)]))

    assert [j["id"] for j in fake.jobs] == ["sync.customers.nightly"]
    # The cron string was parsed by APScheduler's CronTrigger (real).
    assert type(fake.jobs[0]["trigger"]).__name__ == "CronTrigger"
    # A late tick is run, and the schedule's policy decides; never APScheduler's own grace.
    assert fake.jobs[0]["options"] == {
        "misfire_grace_time": None,
        "coalesce": True,
        "max_instances": 1,
    }
    # Firing the registered tick enqueues the schedule's job through the seam.
    fake.jobs[0]["func"]()
    assert queue.envelopes[0].name == "sync.customers.pull"
    assert queue.envelopes[0].payload == {"label": "tick"}
    # The same cron time again owes nothing: the ledger settled it.
    fake.jobs[0]["func"]()
    assert len(queue.envelopes) == 1


def test_apscheduler_start_and_shutdown_delegate(session_factory) -> None:
    fake = _FakeAps()
    scheduler = ApschedulerScheduler(session_factory, scheduler=fake)
    scheduler.start()
    scheduler.shutdown()
    assert fake.started and fake.shut


def test_apscheduler_defaults_to_a_background_scheduler(session_factory) -> None:
    scheduler = ApschedulerScheduler(session_factory)
    assert type(scheduler._scheduler).__name__ == "BackgroundScheduler"


def test_apscheduler_rejects_a_malformed_cron(session_factory) -> None:
    job = _job()
    configure_jobs(JobCatalog([job]))
    scheduler = ApschedulerScheduler(session_factory, scheduler=_FakeAps())
    with pytest.raises(ValueError):
        scheduler.register(_schedule(job, cron="not a cron"))


def test_apscheduler_runs_a_heartbeat_on_its_own_engine(session_factory) -> None:
    fake = _FakeAps()
    beats: list[int] = []
    ApschedulerScheduler(session_factory, scheduler=fake, clock=_Clock(_at(9))).every(
        10, lambda: beats.append(1)
    )
    [entry] = fake.jobs
    assert type(entry["trigger"]).__name__ == "IntervalTrigger"
    assert entry["trigger"].interval == timedelta(seconds=10)
    assert entry["options"]["next_run_time"] == _at(9), "it beats once at start"
    entry["func"]()
    assert beats == [1]


def test_a_restarted_apscheduler_applies_each_schedule_s_misfire_policy(outbox_db) -> None:
    """ADR 0191's exit test, on the adapter `terp jobs scheduler` runs: one scheduler fires
    at nine and stops; another, sharing only the database, starts at half past eleven."""
    job = _job()
    configure_jobs(JobCatalog([job]), queue=OutboxJobQueue())
    catalog = ScheduleCatalog(_hourly(job))

    first = _aps(outbox_db, _Clock(_at(9, 0, 10)))
    first.register_all(catalog)
    first.start()  # settles both: nine o'clock is on time
    assert _queued(outbox_db) == 2
    assert _outcomes(outbox_db) == {"reports.hourly": "fired", "reminders.hourly": "fired"}

    clock = _Clock(_at(11, 30))
    fake = _FakeAps()
    second = _aps(outbox_db, clock, fake)
    second.register_all(catalog)
    settled = {result.schedule: result for result in second.catch_up()}
    late, skipped = settled["reports.hourly"], settled["reminders.hourly"]
    assert (late.outcome, late.slot) == ("late", _at(11)) and late.job_id is not None
    assert (skipped.outcome, skipped.slot, skipped.job_id) == ("skipped", _at(11), None)
    assert _queued(outbox_db) == 3, "ten and eleven folded into one late run; the skip ran nothing"
    assert _records(outbox_db) == {
        "reports.hourly": (_at(11), "late", 2),
        "reminders.hourly": (_at(11), "skipped", 2),
    }
    assert [result.outcome for result in second.catch_up()] == [None, None], "owed once"

    clock.now = _at(12, 0, 2)
    for entry in fake.jobs:
        entry["func"]()  # the noon tick, on time, runs for both
    assert _queued(outbox_db) == 5
    assert set(_outcomes(outbox_db).values()) == {"fired"}


def test_a_first_start_owes_nothing_and_records_where_it_starts(outbox_db) -> None:
    job = _job()
    configure_jobs(JobCatalog([job]), queue=OutboxJobQueue())
    scheduler = _aps(outbox_db, _Clock(_at(9, 20)))
    scheduler.register_all(ScheduleCatalog(_hourly(job)))
    assert [result.outcome for result in scheduler.catch_up()] == ["baseline", "baseline"]
    assert _queued(outbox_db) == 0, "nothing is known about the time before the ledger"


def test_a_tick_the_engine_ran_late_is_a_misfire_too(outbox_db) -> None:
    """A scheduler that was alive but stalled (a suspended host) settles the same way."""
    job = _job()
    configure_jobs(JobCatalog([job]), queue=OutboxJobQueue())
    clock = _Clock(_at(9, 0, 1))
    fake = _FakeAps()
    scheduler = _aps(outbox_db, clock, fake)
    scheduler.register_all(ScheduleCatalog(_hourly(job)))
    scheduler.start()
    clock.now = _at(10, 7)
    for entry in fake.jobs:
        entry["func"]()
    assert _outcomes(outbox_db) == {"reports.hourly": "late", "reminders.hourly": "skipped"}


# --------------------------------------------------------------------------- #
# Celery-beat adapter
# --------------------------------------------------------------------------- #
def test_celery_beat_builds_a_beat_entry_and_tick_task(session_factory) -> None:
    job = _job()
    queue = _CapturingQueue()
    configure_jobs(JobCatalog([job]), queue=queue)
    app = Celery("terp-beat-test")
    beat = CeleryBeatScheduler(app, session_factory, clock=_Clock(_at(2, 0, 3)))
    beat.register_all(ScheduleCatalog([_schedule(job)]))

    entry = beat.beat_schedule["sync.customers.nightly"]
    assert entry["task"] == "terp.schedule.sync.customers.nightly"
    assert isinstance(entry["schedule"], crontab)
    # The tick task is registered on the Celery app; firing it enqueues through the seam.
    assert "terp.schedule.sync.customers.nightly" in app.tasks
    assert app.tasks["terp.schedule.sync.customers.nightly"].run() == "captured"
    assert queue.envelopes[0].name == "sync.customers.pull"
    assert queue.envelopes[0].payload == {"label": "tick"}
    assert app.tasks["terp.schedule.sync.customers.nightly"].run() is None, "already settled"


def test_celery_beat_install_merges_onto_the_app_config(session_factory) -> None:
    job = _job()
    configure_jobs(JobCatalog([job]))
    app = Celery("terp-beat-install-test")
    app.conf.beat_schedule = {"pre-existing": {"task": "x", "schedule": 60.0}}
    beat = CeleryBeatScheduler(app, session_factory)
    beat.register(_schedule(job))
    beat.install()
    assert "pre-existing" in app.conf.beat_schedule  # existing entries preserved
    assert "sync.customers.nightly" in app.conf.beat_schedule


def test_to_crontab_parses_five_fields_and_rejects_others() -> None:
    parsed = _to_crontab("30 4 * * 1")
    assert isinstance(parsed, crontab)
    assert parsed.minute == {30} and parsed.hour == {4}
    with pytest.raises(ValueError, match="5-field cron"):
        _to_crontab("* * *")


def test_a_restarted_beat_applies_each_schedule_s_misfire_policy(outbox_db) -> None:
    """The same exit test on Celery beat: a tick beat fires late on start is settled as the
    misfire it is, and `catch_up` (from beat_init) settles a gap beat never fires for."""
    job = _job()
    configure_jobs(JobCatalog([job]), queue=OutboxJobQueue())
    catalog = ScheduleCatalog(_hourly(job))

    def beat(app: Celery, at: datetime, prefix: str) -> CeleryBeatScheduler:
        # Its own task prefix: Celery shares a task registered under one name across every
        # app in a process, and these two stand for two processes.
        started = CeleryBeatScheduler(
            app,
            lambda: Session(outbox_db),
            task_prefix=prefix,
            ledger=DatabaseScheduleLedger(),
            clock=_Clock(at),
        )
        started.register_all(catalog)
        return started

    first = beat(Celery("terp-beat-first"), _at(9, 0, 4), "first.")
    assert [result.outcome for result in first.catch_up()] == ["fired", "fired"]

    app = Celery("terp-beat-second")
    second = beat(app, _at(11, 30), "second.")
    # Beat's own catch-up fires the reports tick late on start: the ledger calls it late.
    assert app.tasks["second.reports.hourly"].run() is not None
    settled = {result.schedule: result.outcome for result in second.catch_up()}
    assert settled == {"reports.hourly": None, "reminders.hourly": "skipped"}
    assert _records(outbox_db) == {
        "reports.hourly": (_at(11), "late", 2),
        "reminders.hourly": (_at(11), "skipped", 2),
    }
    assert _queued(outbox_db) == 3
