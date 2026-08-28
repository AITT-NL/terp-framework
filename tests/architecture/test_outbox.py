"""Gate for the durable outbox capability (ADR 0045): transactional enqueue, the leased
claim, retry / backoff, dead-letter, at-least-once redelivery, the context-bound worker
run, and the ``require_durable_jobs`` boot guard the in-process default cannot satisfy.

The producer side (durable :class:`OutboxJobQueue` / ``outbox_event_dispatcher``) is driven
against a real ``BaseService`` write so the **atomicity** claim is proven — the outbox row
commits with the business write and a rollback drops both. The consumer side
(:class:`OutboxWorker`) drives synthetic rows over a **file** SQLite database (so the
bookkeeping session and each job's own ``run_job`` session are independent connections),
proving the lease, the retry budget, the dead-letter, and that a drained job's writes are
audited + actor-stamped from the envelope (the jobs design's §7).
"""

from __future__ import annotations

import pathlib
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import Field, Session, SQLModel, create_engine, select

from terp.core import (
    ActorStampedMixin,
    BaseSchema,
    BaseService,
    BaseTable,
    BaseUpdateSchema,
    EventCatalog,
    EventDefinition,
    EventEnvelope,
    EventVisibility,
    JobCatalog,
    JobDefinition,
    JobEnvelope,
    ModuleSpec,
    Policy,
    RetryPolicy,
    create_app,
    emit,
    enqueue,
    is_durable_job_queue,
)
from terp.core.audit import AuditAction, AuditRecord, bind_audit_actor, set_audit_sink
from terp.core.events import configure_events
from terp.core.jobs import active_job_queue, configure_jobs
from terp.core._internal.session_guard import WriteGuardedSession

from terp.capabilities.outbox import (
    KIND_EVENT,
    KIND_JOB,
    STATUS_DEAD_LETTERED,
    STATUS_DISPATCHED,
    STATUS_PENDING,
    DrainResult,
    OutboxJobQueue,
    OutboxMessage,
    OutboxWorker,
    outbox_event_dispatcher,
)
from terp.capabilities.outbox._serde import (
    event_envelope_to_payload,
    job_envelope_to_payload,
    payload_to_event_envelope,
    payload_to_job_envelope,
)
from terp.capabilities.outbox.store import claim_due

# A fixed anchor for deterministic lease / backoff timing (decoupled from real time).
_T0 = datetime(2026, 6, 1, tzinfo=UTC)


# --------------------------------------------------------------------------- #
# Synthetic business model + a service whose writes the worker drives through run_job.
# --------------------------------------------------------------------------- #
class _OutboxDoc(BaseTable, ActorStampedMixin, table=True):
    __tablename__ = "_outbox_doc"
    label: str = Field(max_length=50)


class _OutboxDocCreate(BaseSchema):
    label: str = Field(max_length=50)


class _OutboxDocUpdate(BaseUpdateSchema):
    label: str | None = Field(default=None, max_length=50)


class _OutboxDocService(BaseService[_OutboxDoc, _OutboxDocCreate, _OutboxDocUpdate]):
    model = _OutboxDoc


class _EventPayload(BaseSchema):
    detail: str = Field(max_length=50)


class _Clock:
    """A mutable, injectable clock for deterministic lease / backoff assertions."""

    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture
def engine(tmp_path: pathlib.Path) -> Iterator[object]:
    """A file-backed SQLite engine (independent connections for worker + run_job)."""
    eng = create_engine(f"sqlite:///{tmp_path / 'outbox.db'}")
    SQLModel.metadata.create_all(eng)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def captured_audit() -> Iterator[list[AuditRecord]]:
    """Capture every audit record a drained job emits (the default sink only logs)."""
    records: list[AuditRecord] = []
    set_audit_sink(lambda _session, record, _policy: records.append(record))
    yield records  # the autouse conftest fixture restores the default sink


@pytest.fixture
def subscribe_handler() -> Iterator[Callable[[EventDefinition, Callable[[EventEnvelope], None]], None]]:
    """Subscribe an in-process event handler, cleaning up only the names it adds."""
    from terp.capabilities.eventbus import registry

    added: list[str] = []

    def _sub(event: EventDefinition, handler: Callable[[EventEnvelope], None]) -> None:
        registry.subscribe(event)(handler)
        added.append(event.name)

    yield _sub
    for name in added:
        registry._HANDLERS.pop(name, None)


def _bookkeeping(engine: object) -> Callable[[], Session]:
    return lambda: Session(engine)  # type: ignore[arg-type]


def _job_sessions(engine: object) -> Callable[[], Session]:
    return lambda: WriteGuardedSession(engine)  # type: ignore[arg-type]


def _insert_row(
    engine: object,
    *,
    kind: str = KIND_JOB,
    name: str = "x.y",
    payload: dict | None = None,
    available_at: datetime = _T0,
    attempts: int = 0,
    locked_by: str | None = None,
    locked_until: datetime | None = None,
) -> uuid.UUID:
    """Insert one outbox row directly (controlled timing), returning its id."""
    message = OutboxMessage(
        kind=kind,
        name=name,
        payload=payload if payload is not None else {},
        available_at=available_at,
        attempts=attempts,
        locked_by=locked_by,
        locked_until=locked_until,
    )
    with Session(engine) as session:  # type: ignore[arg-type]
        session.add(message)
        session.commit()
        return message.id


def _job_row(
    engine: object,
    name: str,
    *,
    label: str = "x",
    actor: uuid.UUID | None = None,
    available_at: datetime = _T0,
    attempts: int = 0,
) -> uuid.UUID:
    """Insert a ``kind=job`` row carrying a valid serialized envelope."""
    envelope = JobEnvelope(name=name, payload={"label": label}, actor_id=actor)
    return _insert_row(
        engine,
        kind=KIND_JOB,
        name=name,
        payload=job_envelope_to_payload(envelope),
        available_at=available_at,
        attempts=attempts,
    )


# --------------------------------------------------------------------------- #
# (1) Producer: durable enqueue / dispatch persist a pending row, atomically
# --------------------------------------------------------------------------- #
def test_durable_enqueue_persists_a_pending_job_row(engine: object) -> None:
    job = JobDefinition(name="docs.noop", payload_schema=_OutboxDocCreate, handler=lambda c, p: None)
    configure_jobs(JobCatalog([job]), queue=OutboxJobQueue())
    actor = uuid.uuid4()
    with WriteGuardedSession(engine) as session, bind_audit_actor(actor):  # type: ignore[arg-type]
        job_id = enqueue(session, job=job, payload=_OutboxDocCreate(label="x"), idempotency_key="k1")
    with Session(engine) as session:  # type: ignore[arg-type]
        row = session.exec(select(OutboxMessage)).one()
    assert row.kind == KIND_JOB
    assert row.name == "docs.noop"
    assert row.status == STATUS_PENDING
    assert row.attempts == 0
    assert row.idempotency_key == "k1"
    assert row.payload["actor_id"] == str(actor)  # the envelope carried the actor (§7)
    assert str(row.id) == job_id


def test_enqueue_in_after_write_commits_atomically_with_the_business_write(engine: object) -> None:
    job = JobDefinition(name="docs.noop", payload_schema=_OutboxDocCreate, handler=lambda c, p: None)
    configure_jobs(JobCatalog([job]), queue=OutboxJobQueue())

    class _Svc(_OutboxDocService):
        def _after_write(self, session, entity, action):  # type: ignore[no-untyped-def]
            if action is AuditAction.CREATED:
                enqueue(session, job=job, payload=_OutboxDocCreate(label="follow"))

    with WriteGuardedSession(engine) as session:  # type: ignore[arg-type]
        _Svc().create(session, _OutboxDocCreate(label="business"))
    with Session(engine) as session:  # type: ignore[arg-type]
        assert len(session.exec(select(_OutboxDoc)).all()) == 1
        assert len(session.exec(select(OutboxMessage)).all()) == 1  # atomic: both committed


def test_rollback_drops_the_outbox_row(engine: object) -> None:
    job = JobDefinition(name="docs.noop", payload_schema=_OutboxDocCreate, handler=lambda c, p: None)
    configure_jobs(JobCatalog([job]), queue=OutboxJobQueue())

    class _Boom(RuntimeError):
        pass

    class _Svc(_OutboxDocService):
        def _after_write(self, session, entity, action):  # type: ignore[no-untyped-def]
            enqueue(session, job=job, payload=_OutboxDocCreate(label="follow"))
            raise _Boom()

    with WriteGuardedSession(engine) as session:  # type: ignore[arg-type]
        with pytest.raises(_Boom):
            _Svc().create(session, _OutboxDocCreate(label="business"))
        session.rollback()
    with Session(engine) as session:  # type: ignore[arg-type]
        assert session.exec(select(_OutboxDoc)).all() == []  # business write rolled back
        assert session.exec(select(OutboxMessage)).all() == []  # ... and so did the outbox row


def test_durable_event_dispatcher_persists_a_pending_event_row(engine: object) -> None:
    event = EventDefinition(name="outbox.test.created", payload_schema=_EventPayload)
    configure_events(EventCatalog([event]), dispatcher=outbox_event_dispatcher)
    with WriteGuardedSession(engine) as session:  # type: ignore[arg-type]
        emit(session, event=event, payload=_EventPayload(detail="hi"))
    with Session(engine) as session:  # type: ignore[arg-type]
        row = session.exec(select(OutboxMessage)).one()
    assert row.kind == KIND_EVENT
    assert row.name == "outbox.test.created"
    assert row.status == STATUS_PENDING
    assert row.payload["visibility"] == "internal"
    assert row.payload["payload"]["detail"] == "hi"


# --------------------------------------------------------------------------- #
# (2) Boot guard: the marked durable queue satisfies require_durable_jobs
# --------------------------------------------------------------------------- #
def test_outbox_queue_satisfies_require_durable_jobs() -> None:
    queue = OutboxJobQueue()
    assert is_durable_job_queue(queue)
    spec = ModuleSpec(name="probe", policy=Policy.default())
    create_app([spec], job_queue=queue, require_durable_jobs=True)  # no BootError
    assert active_job_queue() is queue


# --------------------------------------------------------------------------- #
# (3) Claim: lease, skip-active-lease, reclaim-expired, skip-not-yet-due, SKIP LOCKED
# --------------------------------------------------------------------------- #
def test_claim_leases_due_rows_and_a_second_claim_skips_them(engine: object) -> None:
    mid = _insert_row(engine, available_at=_T0)
    lease_until = _T0 + timedelta(seconds=30)
    with Session(engine) as session:  # type: ignore[arg-type]
        claimed = claim_due(session, claim_id="c1", now=_T0, lease_until=lease_until, limit=10)
    assert [m.id for m in claimed] == [mid]
    # the row is now leased (not expired), so a concurrent worker's claim sees nothing
    with Session(engine) as session:  # type: ignore[arg-type]
        again = claim_due(session, claim_id="c2", now=_T0, lease_until=lease_until, limit=10)
    assert again == []


def test_claim_reclaims_an_expired_lease(engine: object) -> None:
    mid = _insert_row(engine, available_at=_T0, locked_by="dead", locked_until=_T0 - timedelta(minutes=1))
    with Session(engine) as session:  # type: ignore[arg-type]
        claimed = claim_due(session, claim_id="c", now=_T0, lease_until=_T0 + timedelta(seconds=30), limit=10)
    assert [m.id for m in claimed] == [mid]  # the crashed worker's lease expired → reclaimed


def test_claim_skips_a_row_not_yet_available(engine: object) -> None:
    _insert_row(engine, available_at=_T0 + timedelta(hours=1))
    with Session(engine) as session:  # type: ignore[arg-type]
        claimed = claim_due(session, claim_id="c", now=_T0, lease_until=_T0 + timedelta(seconds=30), limit=10)
    assert claimed == []


def test_claim_skip_locked_path_is_portable_on_sqlite(engine: object) -> None:
    mid = _insert_row(engine, available_at=_T0)
    with Session(engine) as session:  # type: ignore[arg-type]
        claimed = claim_due(
            session, claim_id="c", now=_T0, lease_until=_T0 + timedelta(seconds=30), limit=10, skip_locked=True
        )
    assert [m.id for m in claimed] == [mid]  # SQLite drops FOR UPDATE; the atomic UPDATE still claims


# --------------------------------------------------------------------------- #
# (4) Worker: a drained job's writes are audited + actor/tenant stamped (§7)
# --------------------------------------------------------------------------- #
def test_worker_runs_job_as_an_audited_actor_stamped_write(
    engine: object, captured_audit: list[AuditRecord]
) -> None:
    actor = uuid.uuid4()
    ran: list[str] = []

    def handler(ctx, payload):  # type: ignore[no-untyped-def]
        ran.append(payload.label)
        _OutboxDocService().create(ctx.session, payload)

    job = JobDefinition(name="docs.create", payload_schema=_OutboxDocCreate, handler=handler)
    configure_jobs(JobCatalog([job]), queue=OutboxJobQueue(), system_actor_id=uuid.uuid4())
    _job_row(engine, "docs.create", label="hello", actor=actor)

    worker = OutboxWorker(_bookkeeping(engine), job_session_factory=_job_sessions(engine))
    assert worker.drain_once() == DrainResult(claimed=1, dispatched=1)
    assert ran == ["hello"]

    with Session(engine) as session:  # type: ignore[arg-type]
        doc = session.exec(select(_OutboxDoc)).one()
        assert doc.created_by_id == actor  # §7: actor re-bound from the envelope
        row = session.exec(select(OutboxMessage)).one()
        assert row.status == STATUS_DISPATCHED
        assert row.dispatched_at is not None
        assert row.locked_by is None and row.locked_until is None
    created = [r for r in captured_audit if r.target_type == "_OutboxDoc" and r.action is AuditAction.CREATED]
    assert created and created[0].actor_id == actor


# --------------------------------------------------------------------------- #
# (5) Worker: retry with backoff, then at-least-once redelivery to success
# --------------------------------------------------------------------------- #
def test_worker_retries_a_failing_job_with_backoff(engine: object) -> None:
    clock = _Clock(_T0)

    def handler(ctx, payload):  # type: ignore[no-untyped-def]
        raise RuntimeError("nope")

    job = JobDefinition(
        name="docs.fail",
        payload_schema=_OutboxDocCreate,
        handler=handler,
        retry=RetryPolicy(max_attempts=3, backoff_seconds=10, backoff_multiplier=2),
    )
    configure_jobs(JobCatalog([job]), queue=OutboxJobQueue())
    _job_row(engine, "docs.fail")

    worker = OutboxWorker(_bookkeeping(engine), job_session_factory=_job_sessions(engine), clock=clock)
    assert worker.drain_once() == DrainResult(claimed=1, retried=1)
    with Session(engine) as session:  # type: ignore[arg-type]
        row = session.exec(select(OutboxMessage)).one()
    assert row.status == STATUS_PENDING
    assert row.attempts == 1
    assert row.last_error.startswith("RuntimeError: nope")
    # backoff for attempt 1 = backoff_seconds * multiplier**0 = 10s (compared tz-naively:
    # SQLite returns DateTime(timezone=True) columns as naive, while PostgreSQL keeps them
    # aware — the claim comparison happens in SQL either way, so only this assertion normalizes).
    assert row.available_at.replace(tzinfo=None) == (_T0 + timedelta(seconds=10)).replace(tzinfo=None)
    assert row.locked_by is None


def test_worker_redelivers_until_success_at_least_once(engine: object) -> None:
    clock = _Clock(_T0)
    calls: list[int] = []

    def handler(ctx, payload):  # type: ignore[no-untyped-def]
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("transient")
        _OutboxDocService().create(ctx.session, payload)

    job = JobDefinition(
        name="docs.flaky",
        payload_schema=_OutboxDocCreate,
        handler=handler,
        retry=RetryPolicy(max_attempts=5, backoff_seconds=5),
    )
    configure_jobs(JobCatalog([job]), queue=OutboxJobQueue())
    _job_row(engine, "docs.flaky")

    worker = OutboxWorker(_bookkeeping(engine), job_session_factory=_job_sessions(engine), clock=clock)
    assert worker.drain_once() == DrainResult(claimed=1, retried=1)  # fails first
    clock.now = _T0 + timedelta(seconds=6)  # advance past the backoff
    assert worker.drain_once() == DrainResult(claimed=1, dispatched=1)  # redelivered → succeeds
    assert len(calls) == 2  # at-least-once: the handler ran twice
    with Session(engine) as session:  # type: ignore[arg-type]
        assert len(session.exec(select(_OutboxDoc)).all()) == 1
        assert session.exec(select(OutboxMessage)).one().status == STATUS_DISPATCHED


# --------------------------------------------------------------------------- #
# (6) Worker: dead-letter after max_attempts (job retry budget + worker default)
# --------------------------------------------------------------------------- #
def test_worker_dead_letters_after_the_jobs_max_attempts(engine: object) -> None:
    clock = _Clock(_T0)

    def handler(ctx, payload):  # type: ignore[no-untyped-def]
        raise RuntimeError("always")

    job = JobDefinition(
        name="docs.dead",
        payload_schema=_OutboxDocCreate,
        handler=handler,
        retry=RetryPolicy(max_attempts=2, backoff_seconds=1),
    )
    configure_jobs(JobCatalog([job]), queue=OutboxJobQueue())
    _job_row(engine, "docs.dead")

    worker = OutboxWorker(_bookkeeping(engine), job_session_factory=_job_sessions(engine), clock=clock)
    assert worker.drain_once() == DrainResult(claimed=1, retried=1)  # attempt 1
    clock.now = _T0 + timedelta(seconds=5)
    assert worker.drain_once() == DrainResult(claimed=1, dead_lettered=1)  # attempt 2 → dead-letter
    with Session(engine) as session:  # type: ignore[arg-type]
        row = session.exec(select(OutboxMessage)).one()
    assert row.status == STATUS_DEAD_LETTERED
    assert row.attempts == 2
    assert row.dead_lettered_at is not None
    assert row.last_error.startswith("RuntimeError: always")


def test_worker_dead_letters_a_job_missing_from_the_catalog(engine: object) -> None:
    # the job was removed by a deploy → run_job cannot resolve it; the worker's default
    # retry budget governs the stale row (and one attempt sends it straight to the DLQ).
    configure_jobs(JobCatalog([]), queue=OutboxJobQueue())
    _job_row(engine, "docs.gone")
    worker = OutboxWorker(
        _bookkeeping(engine),
        job_session_factory=_job_sessions(engine),
        clock=_Clock(_T0),
        retry=RetryPolicy(max_attempts=1),
    )
    assert worker.drain_once() == DrainResult(claimed=1, dead_lettered=1)
    with Session(engine) as session:  # type: ignore[arg-type]
        row = session.exec(select(OutboxMessage)).one()
    assert row.status == STATUS_DEAD_LETTERED
    assert "not registered" in row.last_error


def test_worker_finalize_discards_a_stolen_lease(engine: object) -> None:
    # A slow job outran its lease and another worker reclaimed + dispatched the row
    # mid-flight; the original worker's late finalize must DISCARD its outcome (lost),
    # never clobber the row the new owner now holds — no resurrected re-dispatch of a
    # dispatched row, and no releasing of another worker's lease.
    def handler(ctx, payload):  # type: ignore[no-untyped-def]
        # Simulate worker B reclaiming + dispatching this row while A's job runs.
        with Session(engine) as other:  # type: ignore[arg-type]
            row = other.exec(select(OutboxMessage)).one()
            row.locked_by = "worker-B"
            row.locked_until = None
            row.status = STATUS_DISPATCHED
            row.dispatched_at = _T0
            other.add(row)
            other.commit()

    job = JobDefinition(name="docs.slow", payload_schema=_OutboxDocCreate, handler=handler)
    configure_jobs(JobCatalog([job]), queue=OutboxJobQueue())
    mid = _job_row(engine, "docs.slow")

    worker = OutboxWorker(_bookkeeping(engine), job_session_factory=_job_sessions(engine), clock=_Clock(_T0))
    # A's job ran and "succeeded", but its lease was stolen → the finalize is discarded.
    assert worker.drain_once() == DrainResult(claimed=1, lost=1)
    with Session(engine) as session:  # type: ignore[arg-type]
        row = session.get(OutboxMessage, mid)
    assert row.status == STATUS_DISPATCHED  # the new owner's state, intact
    assert row.locked_by == "worker-B"  # the stale worker did NOT clear the foreign lease


# --------------------------------------------------------------------------- #
# (7) Worker: events — deliver to in-process handlers, dead-letter a failing one
# --------------------------------------------------------------------------- #
def test_worker_delivers_an_event_to_in_process_handlers(
    engine: object, subscribe_handler: Callable[..., None]
) -> None:
    received: list[str] = []
    event = EventDefinition(name="outbox.test.delivered", payload_schema=_EventPayload)
    subscribe_handler(event, lambda envelope: received.append(envelope.payload["detail"]))
    envelope = EventEnvelope(
        name=event.name, visibility=EventVisibility.INTERNAL, payload={"detail": "hello"}, request_id=None
    )
    _insert_row(engine, kind=KIND_EVENT, name=event.name, payload=event_envelope_to_payload(envelope))

    worker = OutboxWorker(_bookkeeping(engine), clock=_Clock(_T0))
    assert worker.drain_once() == DrainResult(claimed=1, dispatched=1)
    assert received == ["hello"]
    with Session(engine) as session:  # type: ignore[arg-type]
        assert session.exec(select(OutboxMessage)).one().status == STATUS_DISPATCHED


def test_worker_dead_letters_a_failing_event(engine: object) -> None:
    def boom(envelope: EventEnvelope) -> None:
        raise RuntimeError("handler down")

    envelope = EventEnvelope(
        name="outbox.test.boom", visibility=EventVisibility.INTERNAL, payload={"detail": "x"}, request_id=None
    )
    _insert_row(engine, kind=KIND_EVENT, name=envelope.name, payload=event_envelope_to_payload(envelope))

    worker = OutboxWorker(
        _bookkeeping(engine), event_dispatcher=boom, clock=_Clock(_T0), retry=RetryPolicy(max_attempts=1)
    )
    assert worker.drain_once() == DrainResult(claimed=1, dead_lettered=1)
    with Session(engine) as session:  # type: ignore[arg-type]
        row = session.exec(select(OutboxMessage)).one()
    assert row.status == STATUS_DEAD_LETTERED
    assert "handler down" in row.last_error


# --------------------------------------------------------------------------- #
# (8) The run() loop: drain until empty, and honour max_cycles
# --------------------------------------------------------------------------- #
def test_run_drains_until_empty(engine: object) -> None:
    job = JobDefinition(name="docs.noop", payload_schema=_OutboxDocCreate, handler=lambda c, p: None)
    configure_jobs(JobCatalog([job]), queue=OutboxJobQueue())
    _job_row(engine, "docs.noop")
    _job_row(engine, "docs.noop")
    worker = OutboxWorker(
        _bookkeeping(engine), job_session_factory=_job_sessions(engine), clock=_Clock(_T0), batch_size=1
    )
    totals = worker.run()  # max_cycles=None → drain until a cycle claims nothing
    assert totals.dispatched == 2
    assert totals.claimed == 2


def test_run_respects_max_cycles(engine: object) -> None:
    job = JobDefinition(name="docs.noop", payload_schema=_OutboxDocCreate, handler=lambda c, p: None)
    configure_jobs(JobCatalog([job]), queue=OutboxJobQueue())
    for _ in range(3):
        _job_row(engine, "docs.noop")
    worker = OutboxWorker(
        _bookkeeping(engine),
        job_session_factory=_job_sessions(engine),
        clock=_Clock(_T0),
        batch_size=1,
        worker_id="w1",
    )
    totals = worker.run(max_cycles=1)  # one cycle only, even though rows remain
    assert totals.claimed == 1 and totals.dispatched == 1


# --------------------------------------------------------------------------- #
# (9) Serde round-trips (envelope <-> stored payload)
# --------------------------------------------------------------------------- #
def test_job_envelope_round_trips_with_and_without_context() -> None:
    actor, tenant = uuid.uuid4(), uuid.uuid4()
    full = JobEnvelope(
        name="a.b",
        payload={"label": "x"},
        idempotency_key="k",
        actor_id=actor,
        tenant_id=tenant,
        request_id="r",
        attempt=3,
    )
    assert payload_to_job_envelope(job_envelope_to_payload(full)) == full
    bare = JobEnvelope(name="a.b", payload={"label": "y"})
    assert payload_to_job_envelope(job_envelope_to_payload(bare)) == bare


def test_event_envelope_round_trips() -> None:
    envelope = EventEnvelope(
        name="a.b", visibility=EventVisibility.RESTRICTED, payload={"d": 1}, request_id="r"
    )
    assert payload_to_event_envelope(event_envelope_to_payload(envelope)) == envelope


# --------------------------------------------------------------------------- #
# (10) Adversarial-audit regressions (2026-06-30): multi-vendor VARCHAR length
#      enforcement at the append chokepoint + a vanished-row finalize.
# --------------------------------------------------------------------------- #
def test_durable_enqueue_rejects_an_over_length_idempotency_key(engine: object) -> None:
    """A key SQLite would silently store but PostgreSQL's ``VARCHAR(200)`` would reject is
    refused early and identically on every backend — so it can never fail only the
    *business* write the outbox row rides on PostgreSQL (which the SQLite gate is blind to).
    """
    job = JobDefinition(name="docs.noop", payload_schema=_OutboxDocCreate, handler=lambda c, p: None)
    configure_jobs(JobCatalog([job]), queue=OutboxJobQueue())
    with WriteGuardedSession(engine) as session:  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="idempotency_key"):
            enqueue(
                session,
                job=job,
                payload=_OutboxDocCreate(label="x"),
                idempotency_key="k" * 201,
            )
    with Session(engine) as session:  # type: ignore[arg-type]
        assert session.exec(select(OutboxMessage)).all() == []  # nothing was persisted


def test_worker_finalize_treats_a_vanished_row_as_lost(engine: object) -> None:
    # A retention purge (or any concurrent delete) removed the row between claim and
    # finalize. The worker must DISCARD its outcome (lost) rather than crash the drain
    # cycle on a None row (``session.get`` returns ``None``).
    def handler(ctx, payload):  # type: ignore[no-untyped-def]
        with Session(engine) as other:  # type: ignore[arg-type]
            other.delete(other.exec(select(OutboxMessage)).one())
            other.commit()

    job = JobDefinition(name="docs.vanish", payload_schema=_OutboxDocCreate, handler=handler)
    configure_jobs(JobCatalog([job]), queue=OutboxJobQueue())
    _job_row(engine, "docs.vanish")

    worker = OutboxWorker(_bookkeeping(engine), job_session_factory=_job_sessions(engine), clock=_Clock(_T0))
    assert worker.drain_once() == DrainResult(claimed=1, lost=1)
    with Session(engine) as session:  # type: ignore[arg-type]
        assert session.exec(select(OutboxMessage)).all() == []


# --------------------------------------------------------------------------- #
# the backlog — telling "no consumer" apart from "idle consumers"
# --------------------------------------------------------------------------- #
def test_an_empty_outbox_reports_nothing_waiting(engine: object) -> None:
    from terp.capabilities.outbox import backlog

    with Session(engine) as session:  # type: ignore[arg-type]
        waiting = backlog(session, now=_T0)
    assert waiting.as_dict() == {
        "pending": 0,
        "due": 0,
        "dead_lettered": 0,
        "oldest_due_at": None,
        "oldest_due_age_seconds": None,
    }


def test_the_backlog_distinguishes_an_unclaimed_row_from_a_scheduled_one(
    engine: object,
) -> None:
    """The whole point of the measurement.

    Before it, a queue with zero consumers and a queue with idle consumers were the
    same table of pending rows, and the reaper could not tell them apart either — it
    scans LAPSED claims, and work nobody claimed has no claim to lapse. What separates
    them is how long the oldest DUE row has been due, so "due" has to mean exactly what
    a worker would claim: not a row scheduled for later, not one a live worker holds.
    """
    from terp.capabilities.outbox import backlog

    now = _T0 + timedelta(hours=4)
    _insert_row(engine, name="stuck", available_at=_T0)
    _insert_row(engine, name="later", available_at=now + timedelta(hours=6))
    _insert_row(
        engine,
        name="in-flight",
        available_at=now - timedelta(seconds=5),
        locked_by="worker-1",
        locked_until=now + timedelta(seconds=55),
    )

    with Session(engine) as session:  # type: ignore[arg-type]
        waiting = backlog(session, now=now)

    assert waiting.pending == 3, "everything undelivered counts as pending"
    assert waiting.due == 1, (
        "only the unclaimed, already-due row is claimable: a row scheduled for later is "
        "not a backlog, and one a live worker holds is not stuck"
    )
    assert waiting.oldest_due_age_seconds == 4 * 3600


def test_an_expired_claim_counts_as_due_again(engine: object) -> None:
    """A crashed worker's rows are reclaimable, so they are backlog again — the same
    `locked_until < now` branch claim_due uses. A measure that drifted from what the
    worker actually claims would report a backlog nobody can drain."""
    from terp.capabilities.outbox import backlog

    now = _T0 + timedelta(minutes=30)
    _insert_row(
        engine,
        name="abandoned",
        available_at=_T0,
        locked_by="worker-that-died",
        locked_until=_T0 + timedelta(minutes=1),
    )
    with Session(engine) as session:  # type: ignore[arg-type]
        waiting = backlog(session, now=now)
    assert (waiting.due, waiting.oldest_due_age_seconds) == (1, 30 * 60)


def test_the_outbox_registers_its_backlog_as_a_health_detail(engine: object) -> None:
    """Installing the distribution is the whole adoption step, as with every other
    capability seam — the capability shipped no router and no operator surface at all,
    so nothing anywhere could report that nothing was draining it."""
    import terp.capabilities.outbox  # noqa: F401  (registers at import)
    from terp.core.health import health_details

    detail = health_details()["outbox"]
    _insert_row(engine, name="stuck", available_at=_T0)
    with Session(engine) as session:  # type: ignore[arg-type]
        reported = detail(session)
    assert reported["pending"] == 1
    assert set(reported) == {
        "pending",
        "due",
        "dead_lettered",
        "oldest_due_at",
        "oldest_due_age_seconds",
    }


def test_a_health_detail_is_never_part_of_the_readiness_verdict() -> None:
    """Readiness answers "route traffic here". A growing backlog is a reason to page
    someone, not to take the instance out of the load balancer — doing that would turn a
    delivery problem into an outage, which is the failure this surface exists to expose
    rather than to cause."""
    import inspect

    from terp.core import health as health_module

    ready_source = inspect.getsource(health_module.build_health_router)
    detail_index = ready_source.index('@router.get("/detail")')
    ready_body = ready_source[: ready_source.index('@router.get("/detail")')]
    assert "health_details" not in ready_body, (
        "the readiness verdict must not consult a registered detail"
    )
    assert detail_index > 0


@pytest.fixture
def isolated_health_details() -> Iterator[None]:
    """Restore the detail registry around a test that registers one.

    It is a capability registration rather than a per-app runtime seam (owners register
    once at import), so nothing resets it between tests -- which means a test that adds
    one has to take it back out, or the next test's registration of the same name fails
    for a reason that has nothing to do with it.
    """
    from terp.core import health as health_module

    snapshot = dict(health_module._details)
    try:
        yield
    finally:
        health_module._details.clear()
        health_module._details.update(snapshot)


def test_a_failing_detail_does_not_blind_the_operator_to_the_others(
    isolated_health_details: None,
) -> None:
    from terp.core.health import health_details, register_health_detail

    def explodes(session: object) -> object:
        raise RuntimeError("probe is broken")

    register_health_detail("explodes", explodes)
    assert "explodes" in health_details()

    # The router reports it in its own slot rather than failing the response: one broken
    # probe must not hide every working one.
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from terp.core.db import get_session
    from terp.core.health import build_health_router

    app = FastAPI()
    app.include_router(build_health_router(expose_detail=True), prefix="/health")
    app.dependency_overrides[get_session] = lambda: _RollbackRecorder()
    response = TestClient(app).get("/health/detail")
    assert response.status_code == 200
    assert response.json()["details"]["explodes"] == {"error": "unavailable"}


class _RollbackRecorder:
    """A stand-in session that records whether the handler rolled it back."""

    def __init__(self) -> None:
        self.rolled_back = False

    def rollback(self) -> None:
        self.rolled_back = True


def test_a_failing_probe_does_not_poison_the_session_for_the_next_one() -> None:
    """The probes share one session, and on PostgreSQL a failed statement aborts
    the transaction. Without a rollback the FIRST failure makes every probe after
    it fail too — precisely the blinding this handler claims to prevent."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from terp.core.db import get_session
    from terp.core.health import build_health_router, register_health_detail

    recorder = _RollbackRecorder()

    def explodes(session: object) -> object:
        raise RuntimeError("probe is broken")

    def works(session: object) -> object:
        return {"fine": True}

    register_health_detail("aaa-explodes", explodes)
    register_health_detail("zzz-works", works)
    app = FastAPI()
    app.include_router(build_health_router(expose_detail=True), prefix="/health")
    app.dependency_overrides[get_session] = lambda: recorder

    details = TestClient(app).get("/health/detail").json()["details"]

    assert recorder.rolled_back, "a raising probe must roll the shared session back"
    assert details["aaa-explodes"] == {"error": "unavailable"}
    assert details["zzz-works"] == {"fine": True}, (
        "the probe after the failure still has to report"
    )


def test_the_detail_route_is_off_unless_asked_for() -> None:
    """This router is PUBLIC — mounted outside the policy guard so an orchestrator
    probe can always reach it — and terp.core sits below every authentication
    capability, so there is nothing here to gate it with. Queue depths and
    timestamps are business signal, so they are opt-in."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from terp.core.db import get_session
    from terp.core.health import build_health_router

    app = FastAPI()
    app.include_router(build_health_router(), prefix="/health")
    app.dependency_overrides[get_session] = lambda: None
    client = TestClient(app)

    assert client.get("/health/detail").status_code == 404
    assert client.get("/health/live").status_code == 200, "liveness stays public"


def test_create_app_does_not_expose_detail_by_default() -> None:
    import inspect

    from terp.core.app import create_app

    parameter = inspect.signature(create_app).parameters["expose_health_detail"]
    assert parameter.default is False


def test_a_second_different_detail_under_one_name_is_refused(
    isolated_health_details: None,
) -> None:
    """Two capabilities silently overwriting each other's report would make the surface
    unreliable in exactly the way it exists to fix."""
    from terp.core.health import register_health_detail

    probe = lambda session: {}  # noqa: E731
    register_health_detail("dup", probe)
    register_health_detail("dup", probe)  # idempotent
    with pytest.raises(ValueError, match="already registered"):
        register_health_detail("dup", lambda session: {"other": True})
