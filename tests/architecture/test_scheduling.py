"""Kernel gate for the scheduler seam (ADR 0047): typed schedule catalog + boot validation.

Mirrors the jobs gate (``test_jobs.py``): a :class:`~terp.core.ScheduleDefinition` references
a typed :class:`~terp.core.JobDefinition` catalog constant, the
:class:`~terp.core.ScheduleCatalog` indexes + rejects duplicates and is boot-validated against
the :class:`~terp.core.JobCatalog`, the :class:`~terp.core.Scheduler` ABC registers schedules,
and :func:`~terp.core.trigger_schedule` fires a schedule by enqueuing its job through the typed
chokepoint — so a scheduled job flows through the active queue with no originating user (the
system actor stands in). The kernel imports no scheduler engine; the adapters live in their own
packages (ADR 0047) with their own suites.
"""

from __future__ import annotations

import pytest
from sqlmodel import Field, Session, create_engine

from terp.core import (
    BaseSchema,
    BootError,
    ControlPlane,
    JobCatalog,
    JobDefinition,
    JobEnvelope,
    JobQueue,
    ModuleSpec,
    Policy,
    ScheduleCatalog,
    ScheduleDefinition,
    Scheduler,
    create_app,
    trigger_schedule,
)
from terp.core.jobs import configure_jobs
from terp.core.scheduling import (
    active_schedule_catalog,
    configure_schedules,
    reset_schedules_runtime,
)


class _Payload(BaseSchema):
    label: str | None = Field(default=None, max_length=50)


def _job() -> JobDefinition:
    return JobDefinition(
        name="sync.customers.pull",
        payload_schema=_Payload,
        handler=lambda ctx, payload: None,
    )


def _schedule(job: JobDefinition | None = None, **kwargs: object) -> ScheduleDefinition:
    return ScheduleDefinition(
        name=kwargs.pop("name", "sync.customers.nightly"),  # type: ignore[arg-type]
        job=job if job is not None else _job(),
        cron=kwargs.pop("cron", "0 2 * * *"),  # type: ignore[arg-type]
        **kwargs,  # type: ignore[arg-type]
    )


class _CapturingQueue(JobQueue):
    def __init__(self) -> None:
        self.envelopes: list[JobEnvelope] = []

    def enqueue(self, session: Session, envelope: JobEnvelope) -> str:
        self.envelopes.append(envelope)
        return "captured"


class _RecordingScheduler(Scheduler):
    def __init__(self) -> None:
        self.registered: list[ScheduleDefinition] = []

    def register(self, schedule: ScheduleDefinition) -> None:
        self.registered.append(schedule)


@pytest.fixture
def session() -> Session:
    return Session(create_engine("sqlite://"))


# --------------------------------------------------------------------------- #
# (1) ScheduleDefinition validates its own shape (typed job, dotted name, cron)
# --------------------------------------------------------------------------- #
def test_schedule_definition_validates_name_job_and_cron() -> None:
    schedule = _schedule()
    assert schedule.name == "sync.customers.nightly"
    assert schedule.cron == "0 2 * * *"
    assert schedule.payload_factory is None

    with pytest.raises(ValueError, match="dotted token"):
        _schedule(name="not a token")
    with pytest.raises(ValueError, match="dotted token"):
        _schedule(name="")
    with pytest.raises(TypeError, match="must be a JobDefinition"):
        ScheduleDefinition(name="x.y", job="nope", cron="* * * * *")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="cron"):
        _schedule(cron="   ")
    with pytest.raises(TypeError, match="payload_factory must be callable"):
        _schedule(payload_factory="nope")


# --------------------------------------------------------------------------- #
# (2) ScheduleCatalog mirrors JobCatalog — index by name, reject duplicates
# --------------------------------------------------------------------------- #
def test_schedule_catalog_indexes_and_rejects_duplicates() -> None:
    schedule = _schedule()
    catalog = ScheduleCatalog([schedule])
    assert catalog.has_name("sync.customers.nightly")
    assert not catalog.has_name("nope")
    assert catalog.get("sync.customers.nightly") is schedule
    assert catalog.get("nope") is None
    assert catalog.names() == ("sync.customers.nightly",)
    assert ScheduleCatalog.default().schedules == ()

    with pytest.raises(ValueError, match="duplicate schedule declaration"):
        ScheduleCatalog([schedule, _schedule()])


def test_catalog_missing_jobs_reports_schedules_with_unregistered_jobs() -> None:
    job = _job()
    job_catalog = JobCatalog([job])
    on_catalog = _schedule(job=job)
    assert ScheduleCatalog([on_catalog]).missing_jobs(job_catalog) == ()

    # A schedule whose job is not in the job catalog is reported (boot drift).
    other = JobDefinition(name="sync.other", payload_schema=_Payload, handler=lambda c, p: None)
    off_catalog = _schedule(job=other, name="sync.other.nightly")
    assert ScheduleCatalog([off_catalog]).missing_jobs(job_catalog) == (off_catalog,)

    # A same-name shadow (different handler) is not the registered job either.
    shadow = JobDefinition(
        name="sync.customers.pull", payload_schema=_Payload, handler=lambda c, p: None
    )
    shadowed = _schedule(job=shadow, name="sync.customers.shadow")
    assert ScheduleCatalog([shadowed]).missing_jobs(job_catalog) == (shadowed,)


# --------------------------------------------------------------------------- #
# (3) Scheduler ABC — register_all registers each schedule
# --------------------------------------------------------------------------- #
def test_scheduler_register_all_registers_each_schedule() -> None:
    catalog = ScheduleCatalog([_schedule(), _schedule(name="sync.customers.hourly", cron="0 * * * *")])
    scheduler = _RecordingScheduler()
    scheduler.register_all(catalog)
    assert [s.name for s in scheduler.registered] == [
        "sync.customers.nightly",
        "sync.customers.hourly",
    ]


# --------------------------------------------------------------------------- #
# (4) trigger_schedule fires by enqueuing the job through the typed chokepoint
# --------------------------------------------------------------------------- #
def test_trigger_schedule_enqueues_with_the_factory_payload(session: Session) -> None:
    job = _job()
    queue = _CapturingQueue()
    configure_jobs(JobCatalog([job]), queue=queue)
    schedule = _schedule(job=job, payload_factory=lambda: _Payload(label="tick"))
    job_id = trigger_schedule(session, schedule)
    assert job_id == "captured"
    assert queue.envelopes[0].name == "sync.customers.pull"
    assert queue.envelopes[0].payload == {"label": "tick"}


def test_trigger_schedule_enqueues_the_default_payload_without_a_factory(
    session: Session,
) -> None:
    job = _job()
    queue = _CapturingQueue()
    configure_jobs(JobCatalog([job]), queue=queue)
    job_id = trigger_schedule(session, _schedule(job=job))  # no payload_factory -> schema()
    assert job_id == "captured"
    assert queue.envelopes[0].payload == {"label": None}


# --------------------------------------------------------------------------- #
# (5) configure / active / reset runtime accessors
# --------------------------------------------------------------------------- #
def test_configure_and_reset_schedules_runtime() -> None:
    assert active_schedule_catalog().schedules == ()
    catalog = ScheduleCatalog([_schedule()])
    configure_schedules(catalog)
    assert active_schedule_catalog() is catalog
    reset_schedules_runtime()
    assert active_schedule_catalog().schedules == ()


# --------------------------------------------------------------------------- #
# (6) control-plane boot validation against the job catalog (via create_app)
# --------------------------------------------------------------------------- #
def test_control_plane_validates_that_schedules_reference_declared_jobs() -> None:
    job = _job()
    spec = ModuleSpec(name="docs", policy=Policy.default())
    # A schedule whose job is registered: clean.
    ok = ControlPlane(jobs=JobCatalog([job]), schedules=ScheduleCatalog([_schedule(job=job)]))
    assert ok.validation_errors([spec]) == ()
    # A schedule whose job is not in the catalog: an error naming both.
    bad = ControlPlane(schedules=ScheduleCatalog([_schedule(job=job)]))  # empty job catalog
    errors = bad.validation_errors([spec])
    assert any("sync.customers.nightly" in e and "sync.customers.pull" in e for e in errors)


def test_create_app_boot_fails_on_a_schedule_with_an_undeclared_job() -> None:
    spec = ModuleSpec(name="docs", policy=Policy.default())
    plane = ControlPlane(schedules=ScheduleCatalog([_schedule()]))  # job not declared
    with pytest.raises(BootError, match="not registered in the jobs catalog"):
        create_app([spec], control_plane=plane)


def test_create_app_wires_the_schedule_catalog() -> None:
    job = _job()
    schedule = _schedule(job=job)
    spec = ModuleSpec(name="docs", policy=Policy.default())
    create_app(
        [spec],
        control_plane=ControlPlane(jobs=JobCatalog([job]), schedules=ScheduleCatalog([schedule])),
    )
    assert active_schedule_catalog().names() == ("sync.customers.nightly",)
