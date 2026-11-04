"""Source custody survives atomic jobs without committing their business writes."""

from __future__ import annotations

import threading
import time
import uuid
from queue import Queue

import pytest
from sqlalchemy import text
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from terp.core import (
    BaseSchema, JobCatalog, JobDefinition, JobEnvelope, LeaseHeldError, LeaseLostError,
)
from terp.core._internal.job_runtime import run_job
from terp.core._internal.session_guard import WriteGuardedSession, fresh_write_scope
from terp.core.jobs import configure_jobs
from terp.core.leases import configure_leases, reset_leases_runtime
from terp.capabilities.leases import DatabaseLeaseStore, ResourceLease
from terp.capabilities.sync import (
    STATUS_FAILED, SyncError, SyncMapping, SyncRecordLog, SyncRun,
)
from terp.capabilities.sync.leasing import (
    SYNC_LEASE_TTL_SECONDS, hold_source, sync_source_resource,
)
from terp.capabilities.sync.service import SyncService

from .test_sync import (
    _Customer, _CustomerCreate, _CustomerService, _FakeSource,
    _LeaseClock, _PushSource, _page, _record,
)


class _Payload(BaseSchema):
    pass


def _execute(engine, handler):
    job = JobDefinition(name="sync.custody-probe", payload_schema=_Payload, handler=handler)
    configure_jobs(JobCatalog([job]))
    run_job(
        JobEnvelope(name=job.name, payload={}, actor_id=uuid.uuid4()),
        session_factory=lambda: WriteGuardedSession(engine),
    )


def _tables(engine):
    SQLModel.metadata.create_all(engine, tables=[
        ResourceLease.__table__, SyncRun.__table__, SyncMapping.__table__,
        SyncRecordLog.__table__, _Customer.__table__,
    ])


@pytest.fixture
def custody():
    clock = _LeaseClock()
    store = DatabaseLeaseStore(clock=clock)
    configure_leases(store)
    yield clock, store
    reset_leases_runtime()


@pytest.fixture
def postgres_engine(terp_pg_url):
    engine = create_engine(terp_pg_url, connect_args={
        "options": "-c lock_timeout=5000 -c statement_timeout=10000",
    })
    _tables(engine)
    yield engine
    engine.dispose()


def _resource():
    return sync_source_resource(tenant_scope="global", entity_type="customers")


def _create_local(session):
    return _CustomerService().create(
        session, _CustomerCreate(name="Synthetic", email="synthetic@example.test"),
    )


@pytest.mark.parametrize("shared_connection", [False, True], ids=["file", "static-pool"])
def test_sqlite_failure_releases_custody_without_committing_business_rows(
    tmp_path, custody, shared_connection,
):
    url = "sqlite://" if shared_connection else f"sqlite:///{tmp_path / 'custody.sqlite'}"
    options = {"poolclass": StaticPool} if shared_connection else {}
    engine = create_engine(url, **options)
    _tables(engine)
    _, store = custody

    class PartialPush(_PushSource):
        def push(self, session):
            super().push(session)
            raise SyncError("synthetic interrupted push")

    try:
        for _ in range(2):
            with pytest.raises(SyncError, match="interrupted push"):
                _execute(engine, lambda ctx, _: SyncService().push(ctx.session, PartialPush(1)))
            with Session(engine) as observer:
                assert store.lease_for(observer, _resource()) is None
                assert observer.exec(select(_Customer)).all() == []
                assert observer.exec(select(SyncMapping)).all() == []
                assert observer.exec(select(SyncRecordLog)).all() == []
        with Session(engine) as observer:
            assert [run.status for run in observer.exec(select(SyncRun)).all()] == [
                STATUS_FAILED, STATUS_FAILED,
            ]
    finally:
        engine.dispose()


def test_postgres_lease_and_heartbeat_are_visible_without_business_commit(postgres_engine, custody):
    engine = postgres_engine
    clock, store = custody

    def handler(ctx, _):
        guard = hold_source(ctx.session, tenant_scope="global", entity_type="customers", holder="worker")
        assert guard is not None
        try:
            with pytest.raises(LeaseHeldError):
                hold_source(ctx.session, tenant_scope="global", entity_type="customers", holder="contender")
            _create_local(ctx.session)
            with Session(engine) as observer:
                before = store.lease_for(observer, _resource())
                assert before is not None and before.holder == "worker"
                assert observer.exec(select(_Customer)).all() == []
            guard.heartbeat()  # The cheap path must not commit business data either.
            clock.advance(SYNC_LEASE_TTL_SECONDS / 2 + 1)
            guard.heartbeat()
            with Session(engine) as observer:
                after = store.lease_for(observer, _resource())
                assert after is not None and after.expires_at > before.expires_at
                assert observer.exec(select(_Customer)).all() == []
            guard.release()
            with Session(engine) as observer:
                assert store.lease_for(observer, _resource()) is not None
            raise SyncError("roll back the business unit")
        finally:
            guard.release()

    with pytest.raises(SyncError):
        _execute(engine, handler)
    with Session(engine) as observer:
        assert observer.exec(select(_Customer)).all() == []
        assert store.lease_for(observer, _resource()) is None


def test_direct_service_releases_source_custody_immediately(tmp_path, custody):
    engine = create_engine(f"sqlite:///{tmp_path / 'direct.sqlite'}")
    _tables(engine)
    _, store = custody
    try:
        with WriteGuardedSession(engine) as session:
            SyncService().pull(session, _FakeSource([_page(
                _record("direct", "v1", name="Direct", email="direct@example.test"),
            )]))
            assert store.lease_for(session, _resource()) is None
        with Session(engine) as observer:
            assert len(observer.exec(select(_Customer)).all()) == 1
            assert len(observer.exec(select(SyncMapping)).all()) == 1
            assert len(observer.exec(select(SyncRecordLog)).all()) == 1
    finally:
        engine.dispose()


@pytest.mark.parametrize("direction", ["pull", "push"])
def test_postgres_final_custody_check_refuses_a_successor_even_without_record_heartbeat(
    postgres_engine, custody, direction,
):
    engine = postgres_engine
    clock, store = custody

    def takeover():
        clock.advance(SYNC_LEASE_TTL_SECONDS + 1)
        with fresh_write_scope(), Session(engine) as other:
            assert store.acquire(other, _resource(), holder="successor", ttl_seconds=600) is not None

    class EmptyPull(_FakeSource):
        def pull(self, cursor):
            takeover()
            return _page()

    class FinishedPush(_PushSource):
        def push(self, session):
            result = super().push(session)
            takeover()
            return result

    source = EmptyPull([]) if direction == "pull" else FinishedPush(3)
    with pytest.raises(LeaseLostError):
        _execute(engine, lambda ctx, _: getattr(SyncService(), direction)(ctx.session, source))
    with Session(engine) as observer:
        assert observer.exec(select(_Customer)).all() == []
        assert store.lease_for(observer, _resource()).holder == "successor"
        run = observer.exec(select(SyncRun)).one()
        assert run.status == STATUS_FAILED
        assert run.updated_count == (3 if direction == "push" else 0)


def test_postgres_heartbeat_refuses_an_expired_holder_after_takeover(postgres_engine, custody):
    engine = postgres_engine
    clock, store = custody

    def handler(ctx, _):
        guard = hold_source(ctx.session, tenant_scope="global", entity_type="customers", holder="old")
        assert guard is not None
        _create_local(ctx.session)
        clock.advance(SYNC_LEASE_TTL_SECONDS + 1)
        with fresh_write_scope(), Session(engine) as other:
            assert store.acquire(other, _resource(), holder="new", ttl_seconds=600) is not None
        try:
            guard.heartbeat()
        finally:
            guard.release()

    with pytest.raises(LeaseLostError):
        _execute(engine, handler)
    with Session(engine) as observer:
        assert observer.exec(select(_Customer)).all() == []
        assert store.lease_for(observer, _resource()).holder == "new"


def test_postgres_final_fence_holds_until_business_commit(postgres_engine, custody):
    engine = postgres_engine
    clock, store = custody
    pid = Queue()
    result = Queue()
    errors = Queue()

    def contender():
        try:
            with Session(engine) as other:
                pid.put(other.scalar(text("SELECT pg_backend_pid()")))
                result.put(store.acquire(other, _resource(), holder="next", ttl_seconds=600))
        except BaseException as exc:
            errors.put(exc)

    worker = threading.Thread(target=contender, daemon=True)

    def handler(ctx, _):
        guard = hold_source(ctx.session, tenant_scope="global", entity_type="customers", holder="first")
        assert guard is not None
        _create_local(ctx.session)
        guard.check()
        clock.advance(SYNC_LEASE_TTL_SECONDS + 1)
        worker.start()
        backend_pid = pid.get(timeout=5)
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as observer:
            deadline = time.monotonic() + 5
            while observer.execute(text(
                "SELECT wait_event_type FROM pg_stat_activity WHERE pid=:pid"
            ), {"pid": backend_pid}).scalar_one() != "Lock":
                assert errors.empty()
                assert time.monotonic() < deadline, "successor did not wait on the commit fence"
                threading.Event().wait(0.01)
        assert result.empty()
        guard.release()  # Must not publish a free source while local data is uncommitted.

    try:
        _execute(engine, handler)
        worker.join(10)
        assert not worker.is_alive()
        if not errors.empty():
            raise errors.get_nowait()
        assert result.get_nowait() is not None
        with Session(engine) as observer:
            assert len(observer.exec(select(_Customer)).all()) == 1
            assert store.lease_for(observer, _resource()).holder == "next"
    finally:
        if worker.ident is not None:
            worker.join(10)


def test_postgres_shared_physical_connection_is_refused_before_business_commit(terp_pg_url, custody):
    engine = create_engine(terp_pg_url, poolclass=StaticPool)
    _tables(engine)

    def handler(ctx, _):
        _create_local(ctx.session)
        hold_source(ctx.session, tenant_scope="global", entity_type="customers", holder="unsafe-pool")

    try:
        with pytest.raises(RuntimeError, match="independent database connections"):
            _execute(engine, handler)
        with Session(engine) as observer:
            assert observer.exec(select(_Customer)).all() == []
            assert observer.exec(select(ResourceLease)).all() == []
    finally:
        engine.dispose()
