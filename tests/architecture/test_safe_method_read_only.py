"""End-to-end: a mutating safe-method (GET) handler fails closed (F2).

The deny-by-default guard authorizes a request by HTTP method — a safe method
(``GET`` / ``HEAD`` / ``OPTIONS``) against the policy's *read* requirement — so
``create_app`` marks a safe-method request read-only and the ``BaseService`` write
chokepoint refuses a mutation during it (``ReadOnlyRequestError`` → generic 500). The
*same* write behind a ``POST`` (the write tier) succeeds, and a safe-method *read*
is unaffected. This proves the ``build_read_only_request_binder`` wiring; it pairs
with the build-time ``safe_methods_are_read_only`` rule.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Field, Session, SQLModel, create_engine

from terp.core import (
    BaseSchema,
    BaseService,
    BaseTable,
    BaseUpdateSchema,
    ModuleSpec,
    Policy,
    SessionDep,
    create_app,
    get_session,
)
from terp.core._internal.session_guard import WriteGuardedSession


class _Memo(BaseTable, table=True):
    __tablename__ = "test_ro_memo"

    text: str = Field(max_length=100)


class _MemoCreate(BaseSchema):
    text: str = Field(max_length=100)


class _MemoUpdate(BaseUpdateSchema):
    text: str | None = None


class _MemoService(BaseService[_Memo, _MemoCreate, _MemoUpdate]):
    model = _Memo


_service = _MemoService()
router = APIRouter(tags=["memo"])


# NB: this router deliberately puts a write behind a GET — the very anti-pattern the
# build-time rule forbids — to exercise the runtime backstop. It lives in arch-exempt
# test code, never in app/ or a capability.
@router.get("/leak", response_model=str)
def leak(session: SessionDep) -> str:
    return str(_service.create(session, _MemoCreate(text="from-get")).id)


@router.post("/", response_model=str, status_code=201)
def make(session: SessionDep) -> str:
    return str(_service.create(session, _MemoCreate(text="from-post")).id)


@router.get("/count", response_model=int)
def count(session: SessionDep) -> int:
    return _service.list(session, skip=0, limit=10)[1]


@pytest.fixture
def client() -> Iterator[TestClient]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    spec = ModuleSpec(
        name="memo",
        router=router,
        policy=Policy.public_write(reason="read-only-request backstop test"),
    )
    app = create_app([spec])

    def _session_override() -> Iterator[Session]:
        # The real app hands out a WriteGuardedSession (terp.core.db.SessionDep); use
        # one here so the read-only-request guard (a WriteGuardedSession control) is in
        # force, not a bare Session that bypasses the chokepoint.
        with WriteGuardedSession(engine) as session:
            yield session

    app.dependency_overrides[get_session] = _session_override
    try:
        # raise_server_exceptions=False so a ReadOnlyRequestError surfaces as the
        # generic 500 envelope (as in production) instead of re-raising into the test.
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        SQLModel.metadata.drop_all(engine)
        engine.dispose()


def test_mutating_get_is_refused(client: TestClient) -> None:
    """A write behind a GET fails closed with a generic 500 — and persists nothing."""
    assert client.get("/api/v1/memo/leak").status_code == 500
    assert client.get("/api/v1/memo/count").json() == 0


def test_same_write_behind_post_succeeds(client: TestClient) -> None:
    """The identical write authorized at the write tier (POST) is allowed and persists."""
    assert client.post("/api/v1/memo/").status_code == 201
    assert client.get("/api/v1/memo/count").json() == 1
