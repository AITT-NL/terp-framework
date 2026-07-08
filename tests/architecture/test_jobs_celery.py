"""Capability gate for ``terp-cap-jobs-celery`` (ADR 0046): the first engine adapter.

Proves Terp's jobs seam (ADR 0043) is genuinely **engine-agnostic**. It drives
:class:`~terp.capabilities.jobs_celery.CeleryJobQueue` and the registered worker task in
Celery's **eager mode** (so no broker is needed) over a real in-memory engine, mirroring
the kernel jobs gate (``tests/architecture/test_jobs.py``):

* the producer ships the envelope to the one canonical Terp task, routed by the catalog's
  ``queue`` hint, and returns the Celery id;
* the worker re-binds the envelope's actor / tenant / request id (the design's §7), so a
  job's writes stay **audited + actor / tenant stamped**, with the system-actor fallback;
* the **same** catalog job + handler runs identically under
  :class:`~terp.core.InProcessJobQueue` and :class:`~terp.capabilities.jobs_celery.CeleryJobQueue`
  — the in-process → engine swap with **zero domain change**;
* the durable marker lets ``create_app(require_durable_jobs=True)`` accept it;
* the job's :class:`~terp.core.RetryPolicy` maps onto Celery's retry (the testable core).

The adapter wraps a heavy broker lib, so it lives in its own suite and is omitted from the
core ``--cov=terp`` gate (the design's §16); this file proves its correctness.
"""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import Iterator
from contextvars import ContextVar

import pytest
from celery import Celery
from sqlalchemy.pool import StaticPool
from sqlmodel import Field, Session, SQLModel, create_engine

from terp.core import (
    ActorStampedMixin,
    BaseSchema,
    BaseService,
    BaseTable,
    BaseUpdateSchema,
    ControlPlane,
    InProcessJobQueue,
    JobCatalog,
    JobContext,
    JobDefinition,
    JobEnvelope,
    ModuleSpec,
    Policy,
    RetryPolicy,
    create_app,
    enqueue,
    is_durable_job_queue,
    register_job_tenant_context,
)
from terp.core.audit import AuditAction, AuditRecord, bind_audit_actor, set_audit_sink
from terp.core.jobs import active_job_queue, configure_jobs, reset_job_tenant_context
from terp.core.scoping import (
    register_scope_predicate,
    registered_scope_predicates,
    reset_scope_predicates,
)

from terp.capabilities.jobs_celery import (
    TERP_JOB_TASK,
    CeleryJobQueue,
    register_terp_worker,
)
from terp.capabilities.jobs_celery._serde import (
    job_envelope_to_kwargs,
    kwargs_to_job_envelope,
)
from terp.capabilities.jobs_celery.worker import (
    _execute_envelope,
    _RetryDirective,
    _retry_countdown,
    _retry_for,
)

# --------------------------------------------------------------------------- #
# Synthetic models + a synthetic tenant scope (distinct table names from
# test_jobs.py so the process-global SQLModel registry never collides).
# --------------------------------------------------------------------------- #
_celery_tenant: ContextVar[uuid.UUID | None] = ContextVar("_celery_test_tenant", default=None)


class _CeleryTenantMixin(SQLModel):
    tenant_id: uuid.UUID | None = Field(
        default_factory=_celery_tenant.get, nullable=True, index=True
    )


class _CeleryDoc(BaseTable, ActorStampedMixin, table=True):
    __tablename__ = "_celery_doc"
    label: str = Field(max_length=50)


class _CeleryTenantDoc(BaseTable, ActorStampedMixin, _CeleryTenantMixin, table=True):
    __tablename__ = "_celery_tenant_doc"
    label: str = Field(max_length=50)


class _DocCreate(BaseSchema):
    label: str = Field(max_length=50)


class _DocUpdate(BaseUpdateSchema):
    label: str | None = Field(default=None, max_length=50)


class _DocService(BaseService[_CeleryDoc, _DocCreate, _DocUpdate]):
    model = _CeleryDoc


class _TenantDocService(BaseService[_CeleryTenantDoc, _DocCreate, _DocUpdate]):
    model = _CeleryTenantDoc


def _doc_job() -> JobDefinition:
    def handler(ctx: JobContext, payload: _DocCreate) -> None:
        _DocService().create(ctx.session, payload)

    return JobDefinition(
        name="celery.docs.create", payload_schema=_DocCreate, handler=handler, queue="syncs"
    )


def _tenant_job() -> JobDefinition:
    def handler(ctx: JobContext, payload: _DocCreate) -> None:
        _TenantDocService().create(ctx.session, payload)

    return JobDefinition(
        name="celery.docs.tenant.create", payload_schema=_DocCreate, handler=handler
    )


def _failing_job(max_attempts: int = 3) -> JobDefinition:
    def handler(ctx: JobContext, payload: _DocCreate) -> None:
        raise RuntimeError("boom")

    return JobDefinition(
        name="celery.docs.fail",
        payload_schema=_DocCreate,
        handler=handler,
        retry=RetryPolicy(max_attempts=max_attempts, backoff_seconds=2.0, backoff_multiplier=2.0),
    )


@contextlib.contextmanager
def _bind_celery_tenant(tenant_id: uuid.UUID | None) -> Iterator[None]:
    token = _celery_tenant.set(tenant_id)
    try:
        yield
    finally:
        _celery_tenant.reset(token)


@pytest.fixture
def engine() -> Iterator[object]:
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
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
    """Register the synthetic tenant predicate + job tenant seam, restoring the prior set."""
    saved = registered_scope_predicates()
    reset_scope_predicates()

    def _predicate(model: type[SQLModel], query):  # type: ignore[no-untyped-def]
        if issubclass(model, _CeleryTenantMixin):
            return query.where(model.tenant_id == _celery_tenant.get())
        return query

    register_scope_predicate(_predicate)
    register_job_tenant_context(read=_celery_tenant.get, bind=_bind_celery_tenant)
    try:
        yield
    finally:
        reset_scope_predicates()
        reset_job_tenant_context()
        for predicate in saved:
            register_scope_predicate(predicate)


class _LocalCelery(Celery):
    def send_task(self, name, args=None, kwargs=None, queue=None, **opts):  # type: ignore[no-untyped-def, override]
        return self.tasks[name].apply(args=args or [], kwargs=kwargs or {})


@pytest.fixture
def eager_app() -> Celery:
    """A Celery app whose ``send_task`` runs the registered task locally — no broker.

    Celery's ``task_always_eager`` is ignored by the low-level ``send_task`` (the API a
    producer uses to dispatch by name without importing the task), so this subclass routes
    ``send_task`` straight to the registered task's ``apply`` — running the **real** worker
    task body inline. Only the broker transport is simulated; the producer serialization,
    the registered task, and the kernel ``run_job`` are all exercised for real.
    """
    return _LocalCelery(f"terp-celery-test-{uuid.uuid4().hex}")


# --------------------------------------------------------------------------- #
# (1) producer — enqueue ships the canonical task, routed by the catalog queue
# --------------------------------------------------------------------------- #
class _FakeResult:
    def __init__(self, task_id: str) -> None:
        self.id = task_id


class _FakeCelery:
    """A stand-in Celery app that records ``send_task`` instead of hitting a broker."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, dict, str]] = []

    def send_task(self, name: str, *, kwargs: dict, queue: str) -> _FakeResult:
        self.sent.append((name, kwargs, queue))
        return _FakeResult("celery-task-id-123")


def test_enqueue_sends_the_canonical_task_routed_by_the_catalog_queue(engine: object) -> None:
    job = _doc_job()  # queue="syncs"
    fake = _FakeCelery()
    configure_jobs(JobCatalog([job]), queue=CeleryJobQueue(fake))  # type: ignore[arg-type]
    actor = uuid.uuid4()
    with Session(engine) as session, bind_audit_actor(actor):  # type: ignore[arg-type]
        job_id = enqueue(
            session, job=job, payload=_DocCreate(label="x"), idempotency_key="k1"
        )
    assert job_id == "celery-task-id-123"  # the Celery task id, stringified
    name, kwargs, queue = fake.sent[0]
    assert name == TERP_JOB_TASK
    assert queue == "syncs"  # routed by the JobDefinition's queue hint, from the catalog
    envelope = kwargs["envelope"]
    assert envelope["name"] == "celery.docs.create"
    assert envelope["actor_id"] == str(actor)  # captured for the §7 re-bind, JSON-serialized
    assert envelope["idempotency_key"] == "k1"
    assert envelope["payload"] == {"label": "x"}  # ids/values, never the ORM/DTO object


def test_enqueue_falls_back_to_the_default_queue_for_an_unknown_job(engine: object) -> None:
    # Calling the adapter directly with an envelope whose job a deploy has since removed:
    # there is no definition to read a queue from, so it routes to "default" and the
    # worker's run_job rejects it fail-closed.
    fake = _FakeCelery()
    configure_jobs(JobCatalog([]))  # empty catalog
    queue = CeleryJobQueue(fake)  # type: ignore[arg-type]
    with Session(engine) as session:  # type: ignore[arg-type]
        queue.enqueue(session, JobEnvelope(name="celery.gone.job", payload={"label": "x"}))
    assert fake.sent[0][2] == "default"


# --------------------------------------------------------------------------- #
# (2) §7 — the worker re-binds the envelope's context (audited + isolated)
# --------------------------------------------------------------------------- #
def test_worker_rebinds_actor_and_tenant_from_the_envelope(
    engine: object, captured_audit: list[AuditRecord], tenant_scope: None, eager_app: Celery
) -> None:
    job = _tenant_job()
    task = register_terp_worker(
        eager_app, task_name=eager_app.main, job_session_factory=lambda: Session(engine)
    )  # type: ignore[arg-type]
    configure_jobs(JobCatalog([job]))  # run_job resolves the handler by name
    actor, tenant = uuid.uuid4(), uuid.uuid4()
    # An envelope as it arrives over the broker — NO ambient actor / tenant context, so the
    # only way the write gets stamped is the worker re-binding from the envelope (§7).
    kwargs = job_envelope_to_kwargs(
        JobEnvelope(
            name="celery.docs.tenant.create",
            payload={"label": "iso"},
            actor_id=actor,
            tenant_id=tenant,
        )
    )
    task.apply(args=[kwargs]).get()  # run the task body locally; surface any error

    with Session(engine) as session, _bind_celery_tenant(tenant):  # type: ignore[arg-type]
        rows = session.exec(_TenantDocService().base_query()).all()
    assert [r.label for r in rows] == ["iso"]
    assert rows[0].created_by_id == actor  # actor re-bound from the envelope
    assert rows[0].tenant_id == tenant  # tenant re-bound + read isolated
    assert [r.action for r in captured_audit] == [AuditAction.CREATED]
    assert captured_audit[0].actor_id == actor
    assert captured_audit[0].target_type == "_CeleryTenantDoc"


def test_worker_falls_back_to_the_system_actor(
    engine: object, captured_audit: list[AuditRecord], eager_app: Celery
) -> None:
    system = uuid.uuid4()
    job = _doc_job()
    task = register_terp_worker(
        eager_app, task_name=eager_app.main, job_session_factory=lambda: Session(engine)
    )  # type: ignore[arg-type]
    configure_jobs(JobCatalog([job]), system_actor_id=system)
    # No originating user on the envelope -> the control-plane system actor stands in.
    kwargs = job_envelope_to_kwargs(
        JobEnvelope(name="celery.docs.create", payload={"label": "sys"}, actor_id=None)
    )
    task.apply(args=[kwargs]).get()

    with Session(engine) as session:  # type: ignore[arg-type]
        rows = session.exec(_DocService().base_query()).all()
    assert rows[0].created_by_id == system
    assert captured_audit[0].actor_id == system


def test_worker_stamps_attempt_from_celery_retry_count(
    engine: object, eager_app: Celery
) -> None:
    seen: list[int] = []

    def handler(ctx: JobContext, payload: _DocCreate) -> None:
        seen.append(ctx.attempt)

    job = JobDefinition(name="celery.probe.attempt", payload_schema=_DocCreate, handler=handler)
    task = register_terp_worker(
        eager_app, task_name=eager_app.main, job_session_factory=lambda: Session(engine)
    )  # type: ignore[arg-type]
    configure_jobs(JobCatalog([job]))
    kwargs = job_envelope_to_kwargs(
        JobEnvelope(name="celery.probe.attempt", payload={"label": "x"})
    )
    task.apply(args=[kwargs]).get()  # a first run -> retries == 0 -> attempt == 1
    assert seen == [1]


# --------------------------------------------------------------------------- #
# (3) the in-process -> Celery swap with ZERO domain change
# --------------------------------------------------------------------------- #
def test_in_process_and_celery_produce_identical_effects(
    engine: object, captured_audit: list[AuditRecord], eager_app: Celery
) -> None:
    job = _doc_job()
    actor = uuid.uuid4()

    # (a) the safe in-process default
    configure_jobs(
        JobCatalog([job]), queue=InProcessJobQueue(session_factory=lambda: Session(engine))
    )
    with Session(engine) as caller, bind_audit_actor(actor):  # type: ignore[arg-type]
        enqueue(caller, job=job, payload=_DocCreate(label="swap"))

    # (b) the Celery adapter — SAME job / handler / payload, only the wired queue differs
    register_terp_worker(
        eager_app, task_name=eager_app.main, job_session_factory=lambda: Session(engine)
    )  # type: ignore[arg-type]
    configure_jobs(JobCatalog([job]), queue=CeleryJobQueue(eager_app, task_name=eager_app.main))
    with Session(engine) as caller, bind_audit_actor(actor):  # type: ignore[arg-type]
        enqueue(caller, job=job, payload=_DocCreate(label="swap"))

    # Both engines wrote an identical audited, actor-stamped row — no domain change.
    with Session(engine) as session:  # type: ignore[arg-type]
        rows = session.exec(_DocService().base_query()).all()
    assert [r.label for r in rows] == ["swap", "swap"]
    assert all(r.created_by_id == actor for r in rows)
    assert [r.action for r in captured_audit] == [AuditAction.CREATED, AuditAction.CREATED]


# --------------------------------------------------------------------------- #
# (4) durability marker + the require_durable_jobs boot guard
# --------------------------------------------------------------------------- #
def test_celery_queue_is_durable_and_boots_under_require_durable_jobs() -> None:
    queue = CeleryJobQueue(Celery("terp-celery-marker"))
    assert is_durable_job_queue(queue)  # the broker survives an app restart
    spec = ModuleSpec(name="thing", policy=Policy.default())
    create_app([spec], control_plane=ControlPlane(), job_queue=queue, require_durable_jobs=True)
    assert active_job_queue() is queue


# --------------------------------------------------------------------------- #
# (5) the testable worker core — RetryPolicy maps onto Celery's retry
# --------------------------------------------------------------------------- #
def test_execute_envelope_success_returns_none_and_writes(
    engine: object, captured_audit: list[AuditRecord]
) -> None:
    job = _doc_job()
    configure_jobs(JobCatalog([job]))
    actor = uuid.uuid4()
    kwargs = job_envelope_to_kwargs(
        JobEnvelope(name="celery.docs.create", payload={"label": "ok"}, actor_id=actor)
    )
    directive = _execute_envelope(
        kwargs, attempt=1, job_session_factory=lambda: Session(engine), default_retry=RetryPolicy()
    )
    assert directive is None
    with Session(engine) as session:  # type: ignore[arg-type]
        rows = session.exec(_DocService().base_query()).all()
    assert rows[0].label == "ok" and rows[0].created_by_id == actor
    assert captured_audit[0].action is AuditAction.CREATED


def test_execute_envelope_returns_a_retry_directive_before_the_budget_is_spent(
    engine: object,
) -> None:
    configure_jobs(JobCatalog([_failing_job(max_attempts=3)]))
    kwargs = job_envelope_to_kwargs(
        JobEnvelope(name="celery.docs.fail", payload={"label": "x"})
    )
    directive = _execute_envelope(
        kwargs, attempt=1, job_session_factory=lambda: Session(engine), default_retry=RetryPolicy()
    )
    assert isinstance(directive, _RetryDirective)
    assert isinstance(directive.exc, RuntimeError)
    assert directive.max_retries == 2  # max_attempts - 1
    assert directive.countdown == 2.0  # backoff_seconds * multiplier ** (attempt - 1)


def test_execute_envelope_reraises_when_the_retry_budget_is_spent(engine: object) -> None:
    configure_jobs(JobCatalog([_failing_job(max_attempts=2)]))
    kwargs = job_envelope_to_kwargs(
        JobEnvelope(name="celery.docs.fail", payload={"label": "x"})
    )
    with pytest.raises(RuntimeError, match="boom"):
        _execute_envelope(
            kwargs,
            attempt=2,
            job_session_factory=lambda: Session(engine),
            default_retry=RetryPolicy(),
        )


def test_retry_countdown_is_exponential_and_capped() -> None:
    policy = RetryPolicy(backoff_seconds=2.0, backoff_multiplier=2.0, max_backoff_seconds=10.0)
    assert _retry_countdown(1, policy) == 2.0
    assert _retry_countdown(2, policy) == 4.0
    assert _retry_countdown(3, policy) == 8.0
    assert _retry_countdown(4, policy) == 10.0  # capped at max_backoff_seconds


def test_retry_for_uses_the_catalog_policy_or_the_default() -> None:
    configure_jobs(JobCatalog([_failing_job(max_attempts=4)]))
    assert _retry_for("celery.docs.fail", RetryPolicy()).max_attempts == 4
    fallback = RetryPolicy(max_attempts=9)
    assert _retry_for("celery.unknown.job", fallback) is fallback


# --------------------------------------------------------------------------- #
# (6) serde round-trips the whole envelope (ids, not entities)
# --------------------------------------------------------------------------- #
def test_serde_round_trips_the_envelope() -> None:
    actor, tenant = uuid.uuid4(), uuid.uuid4()
    original = JobEnvelope(
        name="celery.docs.create",
        payload={"label": "x"},
        idempotency_key="k1",
        actor_id=actor,
        tenant_id=tenant,
        request_id="req-9",
        attempt=2,
    )
    rebuilt = kwargs_to_job_envelope(job_envelope_to_kwargs(original))
    assert rebuilt == original

    # A user-less / single-tenant envelope round-trips with None ids intact.
    bare = JobEnvelope(name="celery.docs.create", payload={"label": "y"})
    rebuilt_bare = kwargs_to_job_envelope(job_envelope_to_kwargs(bare))
    assert rebuilt_bare.actor_id is None and rebuilt_bare.tenant_id is None
