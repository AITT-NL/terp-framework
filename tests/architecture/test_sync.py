"""Gate for ``terp-cap-sync`` (ADR 0050): the reconcile engine on the jobs + scheduler seams.

Proves the design's §14 consumer capability end to end against synthetic models over a real
engine: a registered :class:`SyncSource` (``pull`` reads "System B"; ``apply`` upserts the
local row through an **audited** ``BaseService``), driven by the ``SYNC_PULL`` job the runner
executes post-commit. It exercises

* the reconcile's create / update / unchanged decisions against the :class:`SyncMapping`
  ledger (at-least-once + idempotent — a re-pulled unchanged record is a no-op);
* per-record resilience (a failing ``apply`` is logged ``ACTION_FAILED`` and does not abort
  the run) vs. a catastrophic pull failure (the run closes ``failed`` and the job re-raises so
  the outbox retries);
* cursor resume (the next run pulls from the last **succeeded** run's high-watermark);
* the ``SYNC_PUSH`` direction + its fail-closed default;
* the scheduler seam (``sync_pull_schedule`` -> ``trigger_schedule`` -> reconcile); and
* the read-only admin router (runs, per-record logs, and mappings) over a mounted app.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Field, Session, SQLModel, create_engine, select

from terp.core import (
    BaseSchema,
    BaseService,
    BaseTable,
    BaseUpdateSchema,
    ControlPlane,
    InProcessJobQueue,
    JobCatalog,
    JobEnvelope,
    Principal,
    Roles,
    create_app,
)
from terp.core._internal.job_runtime import run_job
from terp.core.db import get_session
from terp.core.jobs import configure_jobs
from terp.core.scheduling import trigger_schedule

from terp.capabilities.sync import (
    ACTION_CREATED,
    ACTION_FAILED,
    ACTION_UNCHANGED,
    ACTION_UPDATED,
    STATUS_FAILED,
    STATUS_SUCCEEDED,
    SYNC_PULL,
    SYNC_PUSH,
    RemotePage,
    RemoteRecord,
    SyncError,
    SyncMapping,
    SyncRecordLog,
    SyncRun,
    SyncSource,
    register_sync_source,
    registered_sync_sources,
    reset_sync_sources,
    resolve_sync_source,
    sync_pull_schedule,
    sync_push_schedule,
)
from terp.capabilities.sync import module as sync_module

_SYSTEM = uuid.uuid4()  # a stand-in "sync" system actor for the background writes
_ADMIN = Principal(id=uuid.uuid4(), role=Roles.ADMIN)
_ENTITY = "customers"


# --------------------------------------------------------------------------- #
# Synthetic local target: a customer the source syncs from "System B".
# --------------------------------------------------------------------------- #
class _Customer(BaseTable, table=True):
    __tablename__ = "_sync_test_customer"
    name: str = Field(max_length=100)
    email: str = Field(max_length=200)


class _CustomerCreate(BaseSchema):
    name: str = Field(max_length=100)
    email: str = Field(max_length=200)


class _CustomerUpdate(BaseUpdateSchema):
    name: str | None = Field(default=None, max_length=100)
    email: str | None = Field(default=None, max_length=200)


class _CustomerService(BaseService[_Customer, _CustomerCreate, _CustomerUpdate]):
    model = _Customer


# --------------------------------------------------------------------------- #
# Fake sources — the app's half of the seam.
# --------------------------------------------------------------------------- #
def _record(remote_id: str, checksum: str, **payload: str) -> RemoteRecord:
    return RemoteRecord(remote_id=remote_id, checksum=checksum, payload=payload)


def _page(*records: RemoteRecord, next_cursor: str | None = None) -> RemotePage:
    return RemotePage(records=tuple(records), next_cursor=next_cursor)


class _FakeSource(SyncSource):
    """A pull source backed by canned pages; ``apply`` upserts a ``_Customer``."""

    entity_type = _ENTITY

    def __init__(
        self, pages: list[RemotePage], *, fail_apply_on: str | None = None
    ) -> None:
        self._pages = list(pages)
        self.pull_calls: list[str | None] = []
        self._fail_apply_on = fail_apply_on
        self._svc = _CustomerService()

    def pull(self, cursor: str | None) -> RemotePage:
        self.pull_calls.append(cursor)
        return self._pages.pop(0) if self._pages else _page()

    def apply(
        self, session: Session, record: RemoteRecord, local_id: uuid.UUID | None
    ) -> uuid.UUID:
        if record.remote_id == self._fail_apply_on:
            raise ValueError("boom: bad record")
        name, email = record.payload["name"], record.payload["email"]
        if local_id is None:
            return self._svc.create(
                session, _CustomerCreate(name=name, email=email)
            ).id
        current = self._svc.get(session, local_id)
        self._svc.update(
            session,
            local_id,
            _CustomerUpdate(name=name, email=email, version=current.version),
        )
        return local_id


class _FailingPullSource(SyncSource):
    """A source whose remote read fails outright (a catastrophic reconcile failure)."""

    entity_type = _ENTITY

    def __init__(self, message: str = "remote unavailable") -> None:
        self._message = message

    def pull(self, cursor: str | None) -> RemotePage:
        raise SyncError(self._message)

    def apply(
        self, session: Session, record: RemoteRecord, local_id: uuid.UUID | None
    ) -> uuid.UUID:
        raise NotImplementedError  # never reached: pull fails first


class _PushSource(SyncSource):
    """A push-capable source: ``push`` writes ``count`` local rows outward-style."""

    entity_type = _ENTITY

    def __init__(self, count: int) -> None:
        self._count = count
        self._svc = _CustomerService()

    def pull(self, cursor: str | None) -> RemotePage:
        raise NotImplementedError  # push-only source

    def apply(
        self, session: Session, record: RemoteRecord, local_id: uuid.UUID | None
    ) -> uuid.UUID:
        raise NotImplementedError  # push-only source

    def push(self, session: Session) -> int:
        for i in range(self._count):
            self._svc.create(
                session, _CustomerCreate(name=f"local-{i}", email=f"local{i}@x.io")
            )
        return self._count


class _FailingPushSource(_PushSource):
    """A push-capable source whose push fails outright."""

    def __init__(self, message: str) -> None:
        super().__init__(0)
        self._message = message

    def push(self, session: Session) -> int:
        raise SyncError(self._message)


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture
def env() -> Iterator[object]:
    """An in-memory engine (shared connection) with the jobs seam configured."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    configure_jobs(
        JobCatalog([SYNC_PULL, SYNC_PUSH]),
        queue=InProcessJobQueue(session_factory=lambda: Session(engine)),
        system_actor_id=_SYSTEM,
    )
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(autouse=True)
def _reset_sources() -> Iterator[None]:
    """The source registry is process-global — clear it around every test."""
    reset_sync_sources()
    yield
    reset_sync_sources()


def _run(
    engine: object,
    *,
    job: str = "sync.pull",
    entity_type: str = _ENTITY,
    tenant_id: uuid.UUID | None = None,
    envelope_tenant_id: uuid.UUID | None = None,
) -> None:
    """Execute a sync job through the runner (binds the actor + write scope)."""
    payload = {"entity_type": entity_type}
    if tenant_id is not None:
        payload["tenant_id"] = str(tenant_id)
    run_job(
        JobEnvelope(
            name=job, payload=payload, actor_id=_SYSTEM, tenant_id=envelope_tenant_id
        ),
        session_factory=lambda: Session(engine),  # type: ignore[arg-type]
    )


def _runs(engine: object) -> list[SyncRun]:
    with Session(engine) as session:  # type: ignore[arg-type]
        return list(
            session.exec(select(SyncRun).order_by(SyncRun.started_at)).all()
        )


def _customers(engine: object) -> list[_Customer]:
    with Session(engine) as session:  # type: ignore[arg-type]
        return list(session.exec(select(_Customer)).all())


def _logs(engine: object) -> list[SyncRecordLog]:
    with Session(engine) as session:  # type: ignore[arg-type]
        return list(session.exec(select(SyncRecordLog)).all())


# --------------------------------------------------------------------------- #
# (1) The source registry — fail-closed resolution
# --------------------------------------------------------------------------- #
def test_source_registry_registers_resolves_and_fails_closed() -> None:
    assert registered_sync_sources() == ()
    source = _FakeSource([])
    register_sync_source(source)
    assert registered_sync_sources() == (_ENTITY,)
    assert resolve_sync_source(_ENTITY) is source
    with pytest.raises(SyncError, match="no sync source registered"):
        resolve_sync_source("unknown")
    reset_sync_sources()
    assert registered_sync_sources() == ()


def test_module_declares_its_jobs_behind_an_admin_policy() -> None:
    assert sync_module.name == "sync"
    assert {j.name for j in sync_module.jobs} == {"sync.pull", "sync.push"}
    assert sync_module.policy is not None and not sync_module.policy.is_public


# --------------------------------------------------------------------------- #
# (2) The reconcile: create -> update -> unchanged (idempotent), all audited
# --------------------------------------------------------------------------- #
def test_reconcile_creates_then_updates_then_skips_unchanged(env: object) -> None:
    # Run A: an unseen record is created.
    register_sync_source(_FakeSource([_page(_record("r1", "v1", name="Ann", email="a@x.io"))]))
    _run(env)
    # Run B: the same remote id with a new checksum updates the local row.
    register_sync_source(_FakeSource([_page(_record("r1", "v2", name="Ann B", email="a@x.io"))]))
    _run(env)
    # Run C: the same checksum is a no-op (idempotent redelivery).
    register_sync_source(_FakeSource([_page(_record("r1", "v2", name="Ann B", email="a@x.io"))]))
    _run(env)

    runs = _runs(env)
    assert len(runs) == 3
    assert all(r.status == STATUS_SUCCEEDED for r in runs)
    assert sum(r.created_count for r in runs) == 1
    assert sum(r.updated_count for r in runs) == 1
    assert sum(r.processed_count for r in runs) == 3

    # One local row, updated in place (the mapping made B/C address the same row).
    customers = _customers(env)
    assert len(customers) == 1
    assert customers[0].name == "Ann B"

    # One mapping, now carrying the latest checksum.
    with Session(env) as session:  # type: ignore[arg-type]
        mapping = session.exec(select(SyncMapping)).one()
    assert mapping.entity_type == _ENTITY
    assert mapping.remote_id == "r1"
    assert mapping.remote_checksum == "v2"
    assert mapping.local_id == customers[0].id

    # Three immutable record-log lines, one per decision.
    actions = sorted(log.action for log in _logs(env))
    assert actions == sorted([ACTION_CREATED, ACTION_UPDATED, ACTION_UNCHANGED])


def test_reconcile_logs_a_bad_record_without_aborting_the_run(env: object) -> None:
    register_sync_source(
        _FakeSource(
            [
                _page(
                    _record("ok", "v1", name="Good", email="g@x.io"),
                    _record("bad", "v1", name="Bad", email="b@x.io"),
                )
            ],
            fail_apply_on="bad",
        )
    )
    _run(env)

    run = _runs(env)[0]
    assert run.status == STATUS_SUCCEEDED  # a per-record failure is not fatal
    assert run.processed_count == 2
    assert run.created_count == 1
    assert run.failed_count == 1

    # Only the good record produced a local row + a mapping.
    assert [c.name for c in _customers(env)] == ["Good"]
    with Session(env) as session:  # type: ignore[arg-type]
        assert session.exec(select(SyncMapping)).one().remote_id == "ok"

    failed = [log for log in _logs(env) if log.action == ACTION_FAILED]
    assert len(failed) == 1
    assert failed[0].remote_id == "bad"
    assert "boom" in (failed[0].message or "")


def test_reconcile_marks_the_run_failed_and_reraises_on_a_pull_failure(env: object) -> None:
    register_sync_source(_FailingPullSource())
    with pytest.raises(SyncError, match="remote unavailable"):
        _run(env)

    run = _runs(env)[0]
    assert run.status == STATUS_FAILED
    assert run.error is not None and "remote unavailable" in run.error
    assert _customers(env) == []


def test_reconcile_clips_and_sanitizes_a_long_pull_failure(env: object) -> None:
    message = "remote\x00" + (" unavailable" * 300)
    register_sync_source(_FailingPullSource(message))

    with pytest.raises(SyncError):
        _run(env)

    run = _runs(env)[0]
    assert run.status == STATUS_FAILED
    assert run.error is not None
    assert "\x00" not in run.error
    assert run.error.startswith("remote unavailable")
    assert len(run.error) == 2000


def test_reconcile_resumes_from_the_last_succeeded_cursor(env: object) -> None:
    first = _FakeSource([_page(_record("r1", "v1", name="A", email="a@x.io"), next_cursor="cursor-1")])
    register_sync_source(first)
    _run(env)
    assert first.pull_calls == [None]  # the first run starts from no cursor

    second = _FakeSource([_page(next_cursor="cursor-2")])
    register_sync_source(second)
    _run(env)
    assert second.pull_calls == ["cursor-1"]  # resumed from run A's high-watermark

    assert [r.cursor for r in _runs(env)] == ["cursor-1", "cursor-2"]


def test_reconcile_keeps_identical_remote_ids_separate_per_tenant(env: object) -> None:
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    register_sync_source(
        _FakeSource([_page(_record("shared", "a1", name="Tenant A", email="a@x.io"))])
    )
    _run(env, tenant_id=tenant_a)

    register_sync_source(
        _FakeSource([_page(_record("shared", "b1", name="Tenant B", email="b@x.io"))])
    )
    _run(env, tenant_id=tenant_b)

    assert sorted(c.name for c in _customers(env)) == ["Tenant A", "Tenant B"]
    with Session(env) as session:  # type: ignore[arg-type]
        mappings = session.exec(select(SyncMapping).order_by(SyncMapping.remote_checksum)).all()
        runs = session.exec(select(SyncRun).order_by(SyncRun.created_at)).all()
        logs = session.exec(select(SyncRecordLog).order_by(SyncRecordLog.created_at)).all()
    assert [m.remote_id for m in mappings] == ["shared", "shared"]
    assert {m.tenant_id for m in mappings} == {tenant_a, tenant_b}
    assert {r.tenant_id for r in runs} == {tenant_a, tenant_b}
    assert {log.tenant_id for log in logs} == {tenant_a, tenant_b}


def test_job_context_tenant_takes_precedence_over_payload_tenant(env: object) -> None:
    payload_tenant, envelope_tenant = uuid.uuid4(), uuid.uuid4()
    register_sync_source(
        _FakeSource([_page(_record("r1", "v1", name="Ctx", email="ctx@x.io"))])
    )

    _run(env, tenant_id=payload_tenant, envelope_tenant_id=envelope_tenant)

    with Session(env) as session:  # type: ignore[arg-type]
        mapping = session.exec(select(SyncMapping)).one()
        run = session.exec(select(SyncRun)).one()
    assert mapping.tenant_id == envelope_tenant
    assert run.tenant_id == envelope_tenant


# --------------------------------------------------------------------------- #
# (3) The push direction + its fail-closed default
# --------------------------------------------------------------------------- #
def test_push_runs_the_source_push_and_records_the_run(env: object) -> None:
    register_sync_source(_PushSource(3))
    _run(env, job="sync.push")

    run = _runs(env)[0]
    assert run.status == STATUS_SUCCEEDED
    assert run.processed_count == 3
    assert len(_customers(env)) == 3


def test_push_fails_closed_when_the_source_does_not_support_it(env: object) -> None:
    register_sync_source(_FakeSource([]))  # a pull-only source
    with pytest.raises(SyncError, match="does not implement push"):
        _run(env, job="sync.push")

    run = _runs(env)[0]
    assert run.status == STATUS_FAILED
    assert run.error is not None and "does not implement push" in run.error


def test_push_clips_and_sanitizes_a_long_failure(env: object) -> None:
    message = "push\x00" + (" exploded" * 300)
    register_sync_source(_FailingPushSource(message))

    with pytest.raises(SyncError):
        _run(env, job="sync.push")

    run = _runs(env)[0]
    assert run.status == STATUS_FAILED
    assert run.error is not None
    assert "\x00" not in run.error
    assert run.error.startswith("push exploded")
    assert len(run.error) == 2000


# --------------------------------------------------------------------------- #
# (4) The scheduler seam — a schedule enqueues + runs the reconcile
# --------------------------------------------------------------------------- #
def test_pull_schedule_triggers_a_reconcile(env: object) -> None:
    register_sync_source(_FakeSource([_page(_record("r1", "v1", name="Sched", email="s@x.io"))]))
    schedule = sync_pull_schedule(_ENTITY, name="sync.customers.pull", cron="0 * * * *")
    assert schedule.job is SYNC_PULL
    assert schedule.cron == "0 * * * *"

    with Session(env) as session:  # type: ignore[arg-type]
        trigger_schedule(session, schedule)  # in-process queue runs it now

    run = _runs(env)[0]
    assert run.status == STATUS_SUCCEEDED and run.created_count == 1
    assert [c.name for c in _customers(env)] == ["Sched"]


def test_push_schedule_triggers_a_push(env: object) -> None:
    register_sync_source(_PushSource(2))
    schedule = sync_push_schedule(_ENTITY, name="sync.customers.push", cron="*/5 * * * *")
    assert schedule.job is SYNC_PUSH

    with Session(env) as session:  # type: ignore[arg-type]
        trigger_schedule(session, schedule)

    run = _runs(env)[0]
    assert run.status == STATUS_SUCCEEDED and run.processed_count == 2
    assert len(_customers(env)) == 2


# --------------------------------------------------------------------------- #
# (5) The read-only admin router over a mounted app
# --------------------------------------------------------------------------- #
def _client(engine: object) -> TestClient:
    app: FastAPI = create_app(
        [sync_module],
        principal_provider=lambda: _ADMIN,
        control_plane=ControlPlane(jobs=JobCatalog([SYNC_PULL, SYNC_PUSH])),
    )

    def _session_override() -> Iterator[Session]:
        with Session(engine) as session:  # type: ignore[arg-type]
            yield session

    app.dependency_overrides[get_session] = _session_override
    return TestClient(app)


def test_admin_router_surfaces_runs_logs_and_mappings(env: object) -> None:
    tenant_id = uuid.uuid4()
    register_sync_source(
        _FakeSource(
            [
                _page(
                    _record("r1", "v1", name="A", email="a@x.io"),
                    _record("r2", "v1", name="B", email="b@x.io"),
                )
            ]
        )
    )
    _run(env, tenant_id=tenant_id)
    client = _client(env)

    runs = client.get("/api/v1/sync/runs")
    assert runs.status_code == 200, runs.text
    assert runs.json()["total"] == 1
    run_id = runs.json()["items"][0]["id"]
    tenant_runs = client.get("/api/v1/sync/runs", params={"tenant_id": str(tenant_id)})
    assert tenant_runs.status_code == 200
    assert tenant_runs.json()["total"] == 1

    detail = client.get(f"/api/v1/sync/runs/{run_id}")
    assert detail.status_code == 200
    assert detail.json()["created_count"] == 2
    tenant_detail = client.get(
        f"/api/v1/sync/runs/{run_id}", params={"tenant_id": str(tenant_id)}
    )
    assert tenant_detail.status_code == 200
    assert tenant_detail.json()["id"] == run_id
    other_tenant_detail = client.get(
        f"/api/v1/sync/runs/{run_id}", params={"tenant_id": str(uuid.uuid4())}
    )
    assert other_tenant_detail.status_code == 404

    logs = client.get(f"/api/v1/sync/runs/{run_id}/logs")
    assert logs.status_code == 200
    assert logs.json()["total"] == 2
    assert {item["action"] for item in logs.json()["items"]} == {ACTION_CREATED}
    tenant_logs = client.get(
        f"/api/v1/sync/runs/{run_id}/logs", params={"tenant_id": str(tenant_id)}
    )
    assert tenant_logs.status_code == 200
    assert tenant_logs.json()["total"] == 2

    all_mappings = client.get("/api/v1/sync/mappings")
    assert all_mappings.json()["total"] == 2

    filtered = client.get("/api/v1/sync/mappings", params={"entity_type": _ENTITY})
    assert filtered.json()["total"] == 2
    tenant_filtered = client.get(
        "/api/v1/sync/mappings",
        params={"entity_type": _ENTITY, "tenant_id": str(tenant_id)},
    )
    assert tenant_filtered.json()["total"] == 2
    empty = client.get("/api/v1/sync/mappings", params={"entity_type": "nope"})
    assert empty.json()["total"] == 0


def test_admin_router_returns_404_for_an_unknown_run(env: object) -> None:
    client = _client(env)
    missing = client.get(f"/api/v1/sync/runs/{uuid.uuid4()}")
    assert missing.status_code == 404
