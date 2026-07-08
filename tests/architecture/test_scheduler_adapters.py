"""Capability gate for the scheduler engine adapters (ADR 0048): APScheduler + Celery beat.

Both adapters build on the core scheduler seam (ADR 0047) and fire a
:class:`~terp.core.ScheduleDefinition` on its cron by **enqueuing its job through the typed
chokepoint** (:func:`~terp.core.trigger_schedule`) — so the SAME schedule fires identically
whichever engine is wired (the design's §11). These suites run the adapters broker-free (a fake
APScheduler that captures the registered job; a real Celery app whose registered tick task is
invoked directly), proving the tick reaches the active :class:`~terp.core.JobQueue`. The
adapters wrap a heavy engine, so they live in their own suite and are omitted from the core
``--cov=terp`` gate (the design's §16).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from celery import Celery
from celery.schedules import crontab
from sqlmodel import Field, Session, create_engine

from terp.core import (
    BaseSchema,
    JobCatalog,
    JobDefinition,
    JobEnvelope,
    JobQueue,
    ScheduleCatalog,
    ScheduleDefinition,
)
from terp.core.jobs import configure_jobs

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


def _schedule(job: JobDefinition, *, name: str = "sync.customers.nightly", cron: str = "0 2 * * *") -> ScheduleDefinition:
    return ScheduleDefinition(
        name=name, job=job, cron=cron, payload_factory=lambda: _Payload(label="tick")
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


# --------------------------------------------------------------------------- #
# APScheduler adapter
# --------------------------------------------------------------------------- #
class _FakeAps:
    """A stand-in APScheduler that records add_job / start / shutdown (no real threads)."""

    def __init__(self) -> None:
        self.jobs: list[dict] = []
        self.started = False
        self.shut = False

    def add_job(self, func, *, trigger, id, name, replace_existing) -> None:  # type: ignore[no-untyped-def]
        self.jobs.append({"func": func, "trigger": trigger, "id": id, "name": name})

    def start(self) -> None:
        self.started = True

    def shutdown(self, wait: bool = True) -> None:
        self.shut = True


def test_apscheduler_registers_a_cron_job_whose_tick_enqueues(session_factory) -> None:
    job = _job()
    queue = _CapturingQueue()
    configure_jobs(JobCatalog([job]), queue=queue)
    fake = _FakeAps()
    scheduler = ApschedulerScheduler(session_factory, scheduler=fake)
    scheduler.register_all(ScheduleCatalog([_schedule(job)]))

    assert [j["id"] for j in fake.jobs] == ["sync.customers.nightly"]
    # The cron string was parsed by APScheduler's CronTrigger (real).
    assert type(fake.jobs[0]["trigger"]).__name__ == "CronTrigger"
    # Firing the registered tick enqueues the schedule's job through the seam.
    fake.jobs[0]["func"]()
    assert queue.envelopes[0].name == "sync.customers.pull"
    assert queue.envelopes[0].payload == {"label": "tick"}


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


# --------------------------------------------------------------------------- #
# Celery-beat adapter
# --------------------------------------------------------------------------- #
def test_celery_beat_builds_a_beat_entry_and_tick_task(session_factory) -> None:
    job = _job()
    queue = _CapturingQueue()
    configure_jobs(JobCatalog([job]), queue=queue)
    app = Celery("terp-beat-test")
    beat = CeleryBeatScheduler(app, session_factory)
    beat.register_all(ScheduleCatalog([_schedule(job)]))

    entry = beat.beat_schedule["sync.customers.nightly"]
    assert entry["task"] == "terp.schedule.sync.customers.nightly"
    assert isinstance(entry["schedule"], crontab)
    # The tick task is registered on the Celery app; firing it enqueues through the seam.
    assert "terp.schedule.sync.customers.nightly" in app.tasks
    app.tasks["terp.schedule.sync.customers.nightly"].run()
    assert queue.envelopes[0].name == "sync.customers.pull"
    assert queue.envelopes[0].payload == {"label": "tick"}


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
