"""Sync failure journals survive an atomic job without reviving rolled-back work."""

from __future__ import annotations

import uuid

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from terp.core import (
    AuditAction, AuditPolicy, BaseSchema, JobCatalog, JobDefinition, JobEnvelope,
    StaleDataError,
)
from terp.core.audit import configure_audit
from terp.core._internal.job_runtime import run_job
from terp.core._internal.session_guard import WriteGuardedSession
from terp.core.jobs import configure_jobs, register_job_tenant_context
from terp.capabilities.audit import AuditEvent, persist_audit
from terp.capabilities.sync import (
    STATUS_FAILED, STATUS_RUNNING, STATUS_SUCCEEDED,
    RemotePage, SyncError, SyncMapping, SyncRecordLog, SyncRun,
)
from terp.capabilities.sync import service as sync_service
from terp.capabilities.sync.schemas import SyncRunUpdate
from terp.capabilities.tenancy.context import current_tenant_id, tenant_context

from .test_sync import (
    _Customer, _FakeSource, _FailingPullSource, _PushSource, _page, _record,
)


class _Payload(BaseSchema):
    pass


@pytest.fixture
def engine(tmp_path):
    # Separate physical connections: a second journal Session must not accidentally
    # commit the job's business transaction through a shared in-memory connection.
    engine = create_engine(f"sqlite:///{tmp_path / 'sync.sqlite'}")
    SQLModel.metadata.create_all(engine)
    configure_audit(AuditPolicy(), sink=persist_audit)
    register_job_tenant_context(read=current_tenant_id, bind=tenant_context)
    yield engine
    engine.dispose()


def _execute(engine, handler, *, actor=None, tenant=None):
    job = JobDefinition(name="sync.transaction-probe", payload_schema=_Payload, handler=handler)
    configure_jobs(JobCatalog([job]))
    run_job(
        JobEnvelope(
            name=job.name, payload={}, actor_id=actor, tenant_id=tenant,
            request_id="sync-journal-probe",
        ),
        session_factory=lambda: WriteGuardedSession(engine),
    )


class _InterruptedRecords(tuple):
    def __iter__(self):
        yield from super().__iter__()
        raise SyncError("source interrupted after an applied record")


class _InterruptedPull(_FakeSource):
    def __init__(self):
        super().__init__([RemotePage(
            records=_InterruptedRecords([
                _record("r1", "v1", name="Example", email="example@example.test"),
            ]),
            next_cursor="must-not-commit",
        )])


class _InterruptedPush(_PushSource):
    def push(self, session):
        super().push(session)
        raise SyncError("source interrupted after local staging")


@pytest.mark.parametrize("direction", ["pull", "push"])
def test_failed_sync_journals_only_the_attempt_after_business_rollback(engine, direction):
    actor, tenant = uuid.uuid4(), uuid.uuid4()
    source = _InterruptedPull() if direction == "pull" else _InterruptedPush(2)
    tenants_at_audit = []

    def audited(session, record, policy):
        tenants_at_audit.append(current_tenant_id())
        persist_audit(session, record, policy)

    configure_audit(AuditPolicy(), sink=audited)

    def handler(ctx, payload):
        getattr(sync_service.SyncService(), direction)(ctx.session, source, tenant_id=tenant)

    with pytest.raises(SyncError, match="source interrupted"):
        _execute(engine, handler, actor=actor, tenant=tenant)

    with Session(engine) as session:
        run = session.exec(select(SyncRun)).one()
        assert run.status == STATUS_FAILED
        assert run.tenant_id == tenant
        assert run.tenant_scope == str(tenant)
        assert run.cursor is None
        assert run.created_count == run.updated_count == 0
        assert run.finished_at is not None
        assert session.exec(select(_Customer)).all() == []
        assert session.exec(select(SyncMapping)).all() == []
        assert session.exec(select(SyncRecordLog)).all() == []
        audit = session.exec(select(AuditEvent)).one()
        assert audit.target_type == "SyncRun"
        assert audit.target_id == str(run.id)
        assert audit.action == AuditAction.CREATED.value
        assert audit.actor_id == actor
        assert audit.request_id == "sync-journal-probe"
    assert tenants_at_audit and set(tenants_at_audit) == {tenant}
    assert current_tenant_id() is None

    # The failed run cannot advance the next reconcile's cursor, and a valid
    # subsequent run still commits its local record and mapping.
    following = _FakeSource([_page(
        _record("r1", "v1", name="Example", email="example@example.test"),
        next_cursor="committed-cursor",
    )])
    _execute(engine, lambda ctx, _: sync_service.SyncService().pull(
        ctx.session, following, tenant_id=tenant,
    ), actor=actor, tenant=tenant)
    assert following.pull_calls == [None]
    with Session(engine) as session:
        assert len(session.exec(select(_Customer)).all()) == 1
        assert len(session.exec(select(SyncMapping)).all()) == 1
        succeeded = session.exec(select(SyncRun).where(SyncRun.status == STATUS_SUCCEEDED)).one()
        assert succeeded.cursor == "committed-cursor"


def test_direct_service_failure_still_closes_its_committed_run(engine):
    with WriteGuardedSession(engine) as session, pytest.raises(SyncError):
        sync_service.SyncService().pull(session, _FailingPullSource())
    with Session(engine) as session:
        assert session.exec(select(SyncRun)).one().status == STATUS_FAILED


def _caught_failure(ctx, payload):
    try:
        sync_service.SyncService().pull(ctx.session, _FailingPullSource())
    except SyncError:
        pass


def test_handler_catching_a_sync_failure_still_records_the_failed_run(engine):
    _execute(engine, _caught_failure)
    with Session(engine) as session:
        run = session.exec(select(SyncRun)).one()
        assert run.status == STATUS_FAILED
        assert run.version == 2
        audit = session.exec(select(AuditEvent).order_by(AuditEvent.created_at)).all()
        assert [event.action for event in audit] == ["created", "updated"]


@pytest.mark.parametrize("status", [STATUS_FAILED, STATUS_RUNNING, STATUS_SUCCEEDED])
def test_deferred_failure_preserves_an_existing_writer_verdict(engine, status):
    def handler(ctx, payload):
        _caught_failure(ctx, payload)
        run = ctx.session.exec(select(SyncRun)).one()
        sync_service.runs_service().update(ctx.session, run.id, SyncRunUpdate(
            status=status, error="another writer owns this verdict", version=run.version,
        ))

    _execute(engine, handler)
    with Session(engine) as session:
        run = session.exec(select(SyncRun)).one()
        assert run.status == status
        assert run.error == "another writer owns this verdict"
        assert run.version == 2


def test_concurrent_writer_between_journal_read_and_update_keeps_its_verdict(engine, monkeypatch):
    service = sync_service.runs_service()
    original = service.update

    def race(session, run_id, outcome):
        with WriteGuardedSession(engine) as other:
            winner = type(service)()
            current = winner.get(other, run_id)
            winner.update(other, run_id, SyncRunUpdate(
                status=STATUS_FAILED, error="concurrent winner", version=current.version,
            ))
        return original(session, run_id, outcome)

    monkeypatch.setattr(service, "update", race)
    _execute(engine, _caught_failure)
    with Session(engine) as session:
        run = session.exec(select(SyncRun)).one()
        assert run.error == "concurrent winner"
        assert run.version == 2


def test_confirmed_external_push_count_survives_failed_local_finalization(engine, monkeypatch):
    source = _PushSource(3)
    service = sync_service.runs_service()

    def fail_finalization(session, run_id, outcome):
        raise StaleDataError()

    monkeypatch.setattr(service, "update", fail_finalization)
    with pytest.raises(StaleDataError):
        _execute(engine, lambda ctx, _: sync_service.SyncService().push(ctx.session, source))
    with Session(engine) as session:
        run = session.exec(select(SyncRun)).one()
        assert run.status == STATUS_FAILED
        assert run.processed_count == run.updated_count == 3
        assert session.exec(select(_Customer)).all() == []
