"""Worker transaction and lease-finalization regressions over real SQLite sessions."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import Field, SQLModel, Session, create_engine, select

from terp.core import (
    BaseTable,
    BaseSchema,
    BaseUpdateSchema,
    BaseService,
    EventEnvelope,
    EventVisibility,
    InProcessJobQueue,
    JobCatalog,
    JobDefinition,
    RetryPolicy,
    enqueue,
)
from terp.core.jobs import configure_jobs
from terp.core._internal.session_guard import WriteGuardedSession
from terp.core._internal.session_guard import UnauditedWriteError
from terp.core._internal.job_runtime import defer_after_job_transaction, run_job
from terp.core import JobEnvelope
from terp.capabilities.outbox import OutboxWorker
from terp.capabilities.outbox._serde import event_envelope_to_payload
from terp.capabilities.outbox.models import OutboxMessage, KIND_EVENT, STATUS_DISPATCHED


class JobRow(BaseTable, table=True):
    __tablename__ = "worker_transaction_row"
    label: str = Field(max_length=50)


class Payload(BaseSchema):
    label: str = Field(max_length=50)


class Patch(BaseUpdateSchema):
    label: str | None = Field(default=None, max_length=50)


class Rows(BaseService[JobRow, Payload, Patch]):
    model = JobRow


@pytest.fixture
def engine(tmp_path):
    value = create_engine(f"sqlite:///{tmp_path / 'workers.db'}")
    SQLModel.metadata.create_all(value)
    yield value
    value.dispose()


def test_failed_public_enqueue_rolls_back_every_service_write(engine):
    def handler(context, payload):
        Rows().create(context.session, payload)
        raise RuntimeError("synthetic later job failure")

    job = JobDefinition(name="workers.atomic", payload_schema=Payload, handler=handler)
    configure_jobs(
        JobCatalog([job]),
        queue=InProcessJobQueue(session_factory=lambda: WriteGuardedSession(engine)),
    )
    with WriteGuardedSession(engine) as session:
        with pytest.raises(RuntimeError, match="synthetic later job failure"):
            enqueue(session, job=job, payload=Payload(label="committed before failure"))
    with Session(engine) as session:
        assert [row.label for row in session.exec(select(JobRow))] == []


def test_outbox_stale_finalize_preserves_successor_after_lease_check_read(engine):
    now = datetime(2026, 6, 1, tzinfo=UTC)
    envelope = EventEnvelope(
        name="workers.finalization",
        payload={"value": "synthetic"},
        visibility=EventVisibility.INTERNAL,
        request_id=None,
    )
    with Session(engine) as session:
        row = OutboxMessage(
            kind=KIND_EVENT,
            name=envelope.name,
            payload=event_envelope_to_payload(envelope),
            available_at=now,
        )
        session.add(row)
        session.commit()
        row_id = row.id

    successor_results = []
    successor = OutboxWorker(
        lambda: Session(engine),
        clock=lambda: now + timedelta(seconds=2),
        worker_id="successor",
        lease_seconds=30,
        event_dispatcher=lambda envelope: None,
    )

    class PausedAfterRead(Session):
        """A deterministic scheduler: run B after A fetched its lease snapshot.

        Uses separate real SQLite connections and real public drain_once calls;
        never changes framework state or lease data directly.
        """

        def get(self, entity, ident, **kwargs):
            result = super().get(entity, ident, **kwargs)
            if entity is OutboxMessage and not successor_results:
                successor_results.append(successor.drain_once())
            return result

    def failed_delivery(envelope):
        raise RuntimeError("synthetic original worker failure")

    original = OutboxWorker(
        lambda: PausedAfterRead(engine),
        clock=lambda: now,
        worker_id="original",
        lease_seconds=1,
        retry=RetryPolicy(max_attempts=1),
        event_dispatcher=failed_delivery,
    )
    stale_result = original.drain_once()
    assert successor_results[0].dispatched == 1
    assert stale_result.dead_lettered == 0 and stale_result.lost == 1
    with Session(engine) as session:
        row = session.get(OutboxMessage, row_id)
        assert row.status == STATUS_DISPATCHED
        assert row.dispatched_at is not None, (
            "Successor really completed delivery first"
        )
        assert row.dead_lettered_at is None


@pytest.mark.parametrize("fails", [False, True])
def test_job_journals_run_after_completion_without_inheriting_write_authority(
    engine, fails
):
    observations = []
    shared = WriteGuardedSession(engine)
    assert not defer_after_job_transaction(shared, lambda: None)

    def handler(context, payload):
        Rows().create(context.session, payload)

        def journal():
            assert not context.session.in_transaction()
            with pytest.raises(UnauditedWriteError):
                context.session.commit()
            with Session(engine) as reader:
                observations.append([row.label for row in reader.exec(select(JobRow))])

        assert defer_after_job_transaction(context.session, journal)
        if fails:
            raise ValueError("handler failed")

    job = JobDefinition(name="workers.journal", payload_schema=Payload, handler=handler)
    configure_jobs(JobCatalog([job]))
    envelope = JobEnvelope(name=job.name, payload={"label": "one unit"})
    if fails:
        with pytest.raises(ValueError, match="handler failed"):
            run_job(envelope, session_factory=lambda: shared)
    else:
        run_job(envelope, session_factory=lambda: shared)
    assert observations == ([[]] if fails else [["one unit"]])
    assert not defer_after_job_transaction(shared, lambda: None)
    # Reusing a session for a later job cannot run a previous job's callbacks.
    other = JobDefinition(
        name="workers.later", payload_schema=Payload, handler=lambda c, p: None
    )
    configure_jobs(JobCatalog([other]))
    run_job(
        JobEnvelope(name=other.name, payload={"label": "later"}),
        session_factory=lambda: shared,
    )
    assert len(observations) == 1


@pytest.mark.parametrize("handler_fails", [False, True])
def test_a_journal_failure_preserves_the_original_handler_error(
    engine, handler_fails, caplog
):
    calls = []

    def handler(context, payload):
        def bad_journal():
            calls.append("bad")
            raise RuntimeError("journal failed")

        assert defer_after_job_transaction(context.session, bad_journal)
        assert defer_after_job_transaction(context.session, bad_journal)
        assert defer_after_job_transaction(
            context.session, lambda: calls.append("last")
        )
        if handler_fails:
            raise ValueError("original handler error")

    job = JobDefinition(
        name="workers.journal-error", payload_schema=Payload, handler=handler
    )
    configure_jobs(JobCatalog([job]))
    expected = ValueError if handler_fails else RuntimeError
    with pytest.raises(
        expected, match="original handler error" if handler_fails else "journal failed"
    ):
        run_job(
            JobEnvelope(name=job.name, payload={"label": "x"}),
            session_factory=lambda: WriteGuardedSession(engine),
        )
    assert calls == ["bad", "bad", "last"]
    if handler_fails:
        assert "Job journal failed after the handler failed" in caplog.text


def test_a_job_handler_cannot_commit_directly(engine):
    def handler(context, payload):
        context.session.commit()

    job = JobDefinition(
        name="workers.raw-write", payload_schema=Payload, handler=handler
    )
    configure_jobs(JobCatalog([job]))
    with pytest.raises(UnauditedWriteError):
        run_job(
            JobEnvelope(name=job.name, payload={"label": "x"}),
            session_factory=lambda: WriteGuardedSession(engine),
        )
