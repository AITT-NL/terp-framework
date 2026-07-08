"""Kernel gate for the jobs seam (ADR 0043): catalog no-drift, fail-closed enqueue, and
the design's §7 context propagation — a job's writes are audited + actor / tenant stamped.

Drives the typed :func:`terp.core.enqueue` chokepoint and the internal runner against
synthetic models over a real in-memory engine (mirroring ``test_actor_stamping``), so the
highest-risk integration detail — that a *background* worker re-binds the originating
actor / tenant / request id and therefore produces an **audited, tenant-isolated** write
with no special-casing — is proven, with the system-actor fallback, the fail-closed paths,
and the boot guards the end-to-end example app does not reach (keeping 100% line coverage).
"""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import Iterator
from contextvars import ContextVar

import pytest
from pydantic import ValidationError
from sqlalchemy.pool import StaticPool
from sqlmodel import Field, Session, SQLModel, create_engine

from terp.core import (
    ActorStampedMixin,
    BaseSchema,
    BaseService,
    BaseTable,
    BaseUpdateSchema,
    BootError,
    ControlPlane,
    InProcessJobQueue,
    JobCatalog,
    JobContext,
    JobDefinition,
    JobEnvelope,
    JobError,
    JobQueue,
    JobVisibility,
    ModuleSpec,
    Policy,
    RetryPolicy,
    create_app,
    enqueue,
    is_durable_job_queue,
    mark_durable_job_queue,
    register_job_tenant_context,
)
from terp.core.audit import AuditAction, AuditRecord, bind_audit_actor, set_audit_sink
from terp.core.jobs import (
    active_job_catalog,
    active_job_queue,
    active_job_system_actor,
    configure_jobs,
    reset_job_tenant_context,
)
from terp.core.scoping import (
    register_scope_predicate,
    registered_scope_predicates,
    reset_scope_predicates,
)
from terp.core._internal.job_runtime import run_job
from terp.core._internal.session_guard import (
    WriteGuardedSession,
    enter_write_unit,
    read_only_request,
)

# --------------------------------------------------------------------------- #
# Synthetic models + a synthetic tenant scope, mirroring how tenancy really works
# (a model default_factory stamps tenant_id; a registered predicate filters reads).
# --------------------------------------------------------------------------- #
_job_tenant: ContextVar[uuid.UUID | None] = ContextVar("_job_test_tenant", default=None)


class _JobTenantMixin(SQLModel):
    tenant_id: uuid.UUID | None = Field(
        default_factory=_job_tenant.get, nullable=True, index=True
    )


class _JobDoc(BaseTable, ActorStampedMixin, table=True):
    __tablename__ = "_job_doc"
    label: str = Field(max_length=50)


class _JobTenantDoc(BaseTable, ActorStampedMixin, _JobTenantMixin, table=True):
    __tablename__ = "_job_tenant_doc"
    label: str = Field(max_length=50)


class _DocCreate(BaseSchema):
    label: str = Field(max_length=50)


class _DocUpdate(BaseUpdateSchema):
    label: str | None = Field(default=None, max_length=50)


class _EmptyPayload(BaseSchema):
    note: str | None = Field(default=None, max_length=50)


class _DocService(BaseService[_JobDoc, _DocCreate, _DocUpdate]):
    model = _JobDoc


class _TenantDocService(BaseService[_JobTenantDoc, _DocCreate, _DocUpdate]):
    model = _JobTenantDoc


def _tenant_predicate(model: type[SQLModel], query):  # type: ignore[no-untyped-def]
    if issubclass(model, _JobTenantMixin):
        return query.where(model.tenant_id == _job_tenant.get())
    return query


@contextlib.contextmanager
def _bind_job_tenant(tenant_id: uuid.UUID | None) -> Iterator[None]:
    token = _job_tenant.set(tenant_id)
    try:
        yield
    finally:
        _job_tenant.reset(token)


@pytest.fixture
def engine() -> Iterator[object]:
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(eng)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def captured_audit() -> Iterator[list[AuditRecord]]:
    """Capture every audit record a job emits (the default sink only logs)."""
    records: list[AuditRecord] = []
    set_audit_sink(lambda _session, record, _policy: records.append(record))
    yield records  # the autouse conftest fixture restores the default sink


@pytest.fixture
def tenant_scope() -> Iterator[None]:
    """Register the synthetic tenant predicate + job tenant seam, restoring the prior set.

    Saves and restores the global scope-predicate registry (mirroring
    ``test_scope_predicate_registry``) so this test never leaks its predicate; the job
    tenant seam is reset by the autouse conftest fixture.
    """
    saved = registered_scope_predicates()
    reset_scope_predicates()
    register_scope_predicate(_tenant_predicate)
    register_job_tenant_context(read=_job_tenant.get, bind=_bind_job_tenant)
    try:
        yield
    finally:
        reset_scope_predicates()
        reset_job_tenant_context()
        for predicate in saved:
            register_scope_predicate(predicate)


def _doc_job() -> JobDefinition:
    def handler(ctx: JobContext, payload: _DocCreate) -> None:
        _DocService().create(ctx.session, payload)

    return JobDefinition(name="docs.create", payload_schema=_DocCreate, handler=handler)


def _tenant_job() -> JobDefinition:
    def handler(ctx: JobContext, payload: _DocCreate) -> None:
        _TenantDocService().create(ctx.session, payload)

    return JobDefinition(
        name="docs.tenant.create", payload_schema=_DocCreate, handler=handler
    )


# --------------------------------------------------------------------------- #
# (1) JobCatalog mirrors EventCatalog — index by name, reject dupes
# --------------------------------------------------------------------------- #
def test_job_catalog_indexes_and_rejects_duplicates() -> None:
    job = _doc_job()
    catalog = JobCatalog([job])
    assert catalog.has_name("docs.create")
    assert not catalog.has_name("nope")
    assert catalog.get("docs.create") is job
    assert catalog.get("nope") is None
    assert catalog.has_job(job)
    assert catalog.names() == ("docs.create",)
    assert JobCatalog.default().jobs == ()

    with pytest.raises(ValueError, match="duplicate job declaration"):
        JobCatalog([job, _doc_job()])


def test_catalog_missing_jobs_reports_unregistered() -> None:
    registered = _doc_job()
    catalog = JobCatalog([registered])
    other = _tenant_job()
    assert catalog.missing_jobs([registered]) == ()
    assert catalog.missing_jobs([registered, other]) == (other,)
    # A same-name shadow (different handler) is not the registered one.
    shadow = JobDefinition(
        name="docs.create", payload_schema=_DocCreate, handler=lambda ctx, p: None
    )
    assert not catalog.has_job(shadow)


# --------------------------------------------------------------------------- #
# (2) typed definitions validate their own shape
# --------------------------------------------------------------------------- #
def test_job_definition_validates_name_schema_and_handler() -> None:
    handler = lambda ctx, payload: None  # noqa: E731
    JobDefinition(name="sync.customers.pull", payload_schema=_DocCreate, handler=handler)

    with pytest.raises(ValueError, match="dotted token"):
        JobDefinition(name="not a token", payload_schema=_DocCreate, handler=handler)
    with pytest.raises(ValueError, match="dotted token"):
        JobDefinition(name="", payload_schema=_DocCreate, handler=handler)
    with pytest.raises(TypeError, match="model_validate"):
        JobDefinition(name="x.y", payload_schema=object, handler=handler)
    with pytest.raises(TypeError, match="must be callable"):
        JobDefinition(name="x.y", payload_schema=_DocCreate, handler="not callable")  # type: ignore[arg-type]


def test_retry_policy_validates_bounds() -> None:
    policy = RetryPolicy()
    assert policy.max_attempts == 5 and policy.retry_on == (Exception,)
    with pytest.raises(ValueError, match="max_attempts"):
        RetryPolicy(max_attempts=0)
    with pytest.raises(ValueError, match="non-negative"):
        RetryPolicy(backoff_seconds=-1)
    with pytest.raises(ValueError, match="non-negative"):
        RetryPolicy(max_backoff_seconds=-1)


def test_job_visibility_default_is_internal() -> None:
    job = JobDefinition(
        name="x.y",
        payload_schema=_DocCreate,
        handler=lambda c, p: None,
        visibility=JobVisibility.PUBLIC,
    )
    assert job.visibility is JobVisibility.PUBLIC
    assert _doc_job().visibility is JobVisibility.INTERNAL


# --------------------------------------------------------------------------- #
# (3) enqueue is the fail-closed chokepoint (mirrors emit)
# --------------------------------------------------------------------------- #
class _CapturingQueue(JobQueue):
    """A test queue that records the envelope instead of running it."""

    def __init__(self) -> None:
        self.envelopes: list[JobEnvelope] = []

    def enqueue(self, session: Session, envelope: JobEnvelope) -> str:
        self.envelopes.append(envelope)
        return "captured"


def test_enqueue_rejects_unregistered_and_shadowed_jobs(engine: object) -> None:
    job = _doc_job()
    configure_jobs(JobCatalog([job]), queue=_CapturingQueue())
    with Session(engine) as session:  # type: ignore[arg-type]
        # A job not in the catalog is refused.
        with pytest.raises(JobError, match="not registered"):
            enqueue(session, job=_tenant_job(), payload=_DocCreate(label="x"))
        # A same-name shadow (different handler) is refused too.
        shadow = JobDefinition(
            name="docs.create", payload_schema=_DocCreate, handler=lambda c, p: None
        )
        with pytest.raises(JobError, match="does not match"):
            enqueue(session, job=shadow, payload=_DocCreate(label="x"))


def test_enqueue_captures_context_and_validates_payload(
    engine: object, tenant_scope: None
) -> None:
    job = _tenant_job()
    queue = _CapturingQueue()
    configure_jobs(JobCatalog([job]), queue=queue)
    actor, tenant = uuid.uuid4(), uuid.uuid4()
    with Session(engine) as session, bind_audit_actor(actor), _bind_job_tenant(tenant):
        job_id = enqueue(
            session, job=job, payload=_DocCreate(label="x"), idempotency_key="k1"
        )
    assert job_id == "captured"
    envelope = queue.envelopes[0]
    # The originating actor + tenant are captured for the worker to re-bind (§7).
    assert envelope.actor_id == actor
    assert envelope.tenant_id == tenant
    assert envelope.idempotency_key == "k1"
    assert envelope.payload == {"label": "x"}  # JSON-serialized, not the ORM/DTO object


def test_enqueue_validates_payload_against_the_schema(engine: object) -> None:
    job = _doc_job()
    configure_jobs(JobCatalog([job]), queue=_CapturingQueue())
    with Session(engine) as session:  # type: ignore[arg-type]
        with pytest.raises(ValidationError):
            enqueue(session, job=job, payload={"wrong": "field"})


def test_enqueue_accepts_a_mapping_or_none_payload(engine: object) -> None:
    job = JobDefinition(
        name="probe.empty", payload_schema=_EmptyPayload, handler=lambda c, p: None
    )
    queue = _CapturingQueue()
    configure_jobs(JobCatalog([job]), queue=queue)
    with Session(engine) as session:  # type: ignore[arg-type]
        enqueue(session, job=job, payload={"note": "hi"})  # mapping -> model_validate
        enqueue(session, job=job, payload=None)  # None -> schema()
    assert queue.envelopes[0].payload == {"note": "hi"}
    assert queue.envelopes[1].payload == {"note": None}


# --------------------------------------------------------------------------- #
# (4) §7 — the worker re-binds the envelope's context; writes stay audited + stamped
# --------------------------------------------------------------------------- #
def test_run_job_rebinds_actor_so_writes_are_audited_and_stamped(
    engine: object, captured_audit: list[AuditRecord]
) -> None:
    job = _doc_job()
    configure_jobs(JobCatalog([job]))
    actor = uuid.uuid4()
    # An envelope built with no ambient context — the runner must bind from the envelope.
    envelope = JobEnvelope(name="docs.create", payload={"label": "x"}, actor_id=actor)
    run_job(envelope, session_factory=lambda: Session(engine))  # type: ignore[arg-type]

    with Session(engine) as session:  # type: ignore[arg-type]
        rows = session.exec(_DocService().base_query()).all()
    assert len(rows) == 1
    assert rows[0].created_by_id == actor  # actor-stamped from the envelope
    # The write is audited, with the envelope's actor on the record.
    assert [r.action for r in captured_audit] == [AuditAction.CREATED]
    assert captured_audit[0].actor_id == actor
    assert captured_audit[0].target_type == "_JobDoc"


def test_run_job_falls_back_to_the_configured_system_actor(
    engine: object, captured_audit: list[AuditRecord]
) -> None:
    system = uuid.uuid4()
    configure_jobs(JobCatalog([_doc_job()]), system_actor_id=system)
    # No originating user (actor_id=None) -> the control-plane system actor stands in.
    envelope = JobEnvelope(name="docs.create", payload={"label": "x"}, actor_id=None)
    run_job(envelope, session_factory=lambda: Session(engine))  # type: ignore[arg-type]

    with Session(engine) as session:  # type: ignore[arg-type]
        rows = session.exec(_DocService().base_query()).all()
    assert rows[0].created_by_id == system
    assert captured_audit[0].actor_id == system


def test_run_job_rebinds_tenant_so_writes_are_isolated(
    engine: object, tenant_scope: None
) -> None:
    configure_jobs(JobCatalog([_tenant_job()]))
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    factory = lambda: Session(engine)  # noqa: E731

    # Two jobs, each under a different tenant carried only by the envelope.
    run_job(JobEnvelope(name="docs.tenant.create", payload={"label": "a"}, tenant_id=tenant_a), session_factory=factory)
    run_job(JobEnvelope(name="docs.tenant.create", payload={"label": "b"}, tenant_id=tenant_b), session_factory=factory)

    # Each row is tenant-stamped from its envelope...
    with Session(engine) as session, _bind_job_tenant(tenant_a):
        rows_a = _TenantDocService().base_query()
        visible_a = session.exec(rows_a).all()
    assert [r.label for r in visible_a] == ["a"]  # ...and a read is tenant-isolated
    assert visible_a[0].tenant_id == tenant_a


def test_in_process_queue_runs_the_handler_through_enqueue(
    engine: object, captured_audit: list[AuditRecord]
) -> None:
    job = _doc_job()
    configure_jobs(JobCatalog([job]), queue=InProcessJobQueue(session_factory=lambda: Session(engine)))
    actor = uuid.uuid4()
    with Session(engine) as caller, bind_audit_actor(actor):
        job_id = enqueue(caller, job=job, payload=_DocCreate(label="x"), idempotency_key="k")
    assert job_id == "k"  # the in-process queue returns the idempotency key
    with Session(engine) as session:  # type: ignore[arg-type]
        rows = session.exec(_DocService().base_query()).all()
    assert len(rows) == 1 and rows[0].created_by_id == actor


def test_in_process_queue_uses_the_default_session_factory_and_job_id() -> None:
    seen: list[tuple[str, uuid.UUID | None, int]] = []

    def handler(ctx: JobContext, payload: _EmptyPayload) -> None:
        seen.append((type(ctx.session).__name__, ctx.actor_id, ctx.attempt))

    job = JobDefinition(name="probe.noop", payload_schema=_EmptyPayload, handler=handler)
    configure_jobs(JobCatalog([job]))  # default queue -> default (write-guarded) session
    queue = active_job_queue()
    job_id = queue.enqueue(
        Session(create_engine("sqlite://")),
        JobEnvelope(name="probe.noop", payload={}, attempt=3),
    )
    assert seen == [("WriteGuardedSession", None, 3)]
    assert job_id.startswith("probe.noop:")  # no idempotency key -> name:timestamp id


def test_run_job_context_exposes_request_id_and_attempt(engine: object) -> None:
    seen: list[JobContext] = []
    job = JobDefinition(
        name="probe.ctx",
        payload_schema=_EmptyPayload,
        handler=lambda ctx, payload: seen.append(ctx),
    )
    configure_jobs(JobCatalog([job]))
    run_job(
        JobEnvelope(name="probe.ctx", payload={}, request_id="req-7", attempt=2),
        session_factory=lambda: Session(engine),  # type: ignore[arg-type]
    )
    assert seen[0].request_id == "req-7"
    assert seen[0].attempt == 2


# --------------------------------------------------------------------------- #
# (5) fail-closed paths
# --------------------------------------------------------------------------- #
def test_run_job_fails_closed_on_an_unknown_envelope(engine: object) -> None:
    configure_jobs(JobCatalog([]))  # empty catalog
    with pytest.raises(JobError, match="cannot resolve a handler"):
        run_job(
            JobEnvelope(name="docs.create", payload={"label": "x"}),
            session_factory=lambda: Session(engine),  # type: ignore[arg-type]
        )


def test_run_job_propagates_a_raising_handler(engine: object) -> None:
    class _Boom(RuntimeError):
        pass

    def handler(ctx: JobContext, payload: _EmptyPayload) -> None:
        raise _Boom()

    job = JobDefinition(name="probe.boom", payload_schema=_EmptyPayload, handler=handler)
    configure_jobs(JobCatalog([job]))
    with pytest.raises(_Boom):
        run_job(
            JobEnvelope(name="probe.boom", payload={}),
            session_factory=lambda: Session(engine),  # type: ignore[arg-type]
        )


def test_run_job_commits_independently_of_an_enclosing_write_depth(
    engine: object, captured_audit: list[AuditRecord]
) -> None:
    # A job enqueued from *inside* an audited write (e.g. an _after_write hook) runs the
    # in-process queue inline, in the caller's context — so the runner must NOT inherit the
    # enclosing write depth, or the job's own _save would defer its commit to an "outer"
    # unit on a different session that never commits it (a silently lost, unaudited write).
    configure_jobs(JobCatalog([_doc_job()]))
    actor = uuid.uuid4()
    with enter_write_unit():  # simulate enqueuing from within a BaseService write (depth>0)
        run_job(
            JobEnvelope(name="docs.create", payload={"label": "x"}, actor_id=actor),
            session_factory=lambda: Session(engine),  # type: ignore[arg-type]
        )
    with Session(engine) as session:  # type: ignore[arg-type]
        rows = session.exec(_DocService().base_query()).all()
    assert len(rows) == 1  # the job committed as its own independent, audited unit
    assert rows[0].created_by_id == actor
    assert [r.action for r in captured_audit] == [AuditAction.CREATED]


def test_run_job_writes_despite_a_read_only_request(engine: object) -> None:
    # A job enqueued during a safe (GET/HEAD/OPTIONS) request runs inline in that
    # read-only context; the worker is its own unit of work at the envelope's authority,
    # so its writes must NOT be blocked by the request's read-only flag. Uses the real
    # write-guarded session (the in-process default), where the flag would otherwise bite.
    configure_jobs(JobCatalog([_doc_job()]))
    with read_only_request(True):
        run_job(
            JobEnvelope(name="docs.create", payload={"label": "x"}),
            session_factory=lambda: WriteGuardedSession(engine),  # type: ignore[arg-type]
        )
    with Session(engine) as session:  # type: ignore[arg-type]
        rows = session.exec(_DocService().base_query()).all()
    assert len(rows) == 1


# --------------------------------------------------------------------------- #
# (6) durable marker + accessors
# --------------------------------------------------------------------------- #
def test_durable_job_queue_marker() -> None:
    assert not is_durable_job_queue(None)
    assert not is_durable_job_queue(InProcessJobQueue())
    durable = mark_durable_job_queue(InProcessJobQueue())
    assert is_durable_job_queue(durable)


def test_configure_jobs_defaults_to_an_in_process_queue() -> None:
    configure_jobs(JobCatalog([_doc_job()]))
    assert isinstance(active_job_queue(), InProcessJobQueue)
    assert active_job_catalog().names() == ("docs.create",)
    assert active_job_system_actor() is None


# --------------------------------------------------------------------------- #
# (7) control-plane boot validation + boot guards (via create_app)
# --------------------------------------------------------------------------- #
def test_control_plane_validates_declared_jobs() -> None:
    job = _doc_job()
    spec = ModuleSpec(name="docs", policy=Policy.default(), jobs=(job,))
    assert ControlPlane(jobs=JobCatalog([job])).validation_errors([spec]) == ()
    errors = ControlPlane().validation_errors([spec])  # empty catalog
    assert any("not registered in the jobs catalog" in e for e in errors)
    assert any("docs.create" in e for e in errors)


def test_create_app_boot_fails_on_an_undeclared_job() -> None:
    spec = ModuleSpec(name="docs", policy=Policy.default(), jobs=(_doc_job(),))
    with pytest.raises(BootError, match="not registered in the jobs catalog"):
        create_app([spec], control_plane=ControlPlane())


def test_create_app_wires_the_catalog_and_system_actor() -> None:
    job = _doc_job()
    system = uuid.uuid4()
    spec = ModuleSpec(name="docs", policy=Policy.default(), jobs=(job,))
    queue = InProcessJobQueue()
    create_app(
        [spec],
        control_plane=ControlPlane(jobs=JobCatalog([job]), job_system_actor_id=system),
        job_queue=queue,
    )
    assert active_job_catalog().names() == ("docs.create",)
    assert active_job_queue() is queue
    assert active_job_system_actor() == system


def test_create_app_requires_a_durable_queue_when_asked() -> None:
    spec = ModuleSpec(name="thing", policy=Policy.default())
    with pytest.raises(BootError, match="not a durable"):
        create_app([spec], require_durable_jobs=True)

    durable = mark_durable_job_queue(InProcessJobQueue())
    create_app([spec], job_queue=durable, require_durable_jobs=True)
    assert active_job_queue() is durable
