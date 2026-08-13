"""End-to-end: a route that declares itself pure is held to it, both halves.

``terp.core.routing.read_only`` is how a handler says "unsafe verb, pure
computation" — the ``POST`` that validates a candidate document or previews an
import, which is a ``POST`` because its input is a body and not because it writes.
Undeclared, such a route is pure only by the *absence* of a write: a guarantee
made of missing code, which holds until an edit adds a line and which nothing is
prompted to check.

The declaration makes it enforceable twice over, which is the same two-layer
discipline ``safe_methods_are_read_only`` gets:

* build time — ``declared_read_only_routes_do_not_write`` flags a decorated
  handler that calls a mutating service method;
* run time — ``create_app``'s binder marks the request read-only, so a write the
  rule could not see statically (through a helper, a subscriber) still fails
  closed at the chokepoint.

Authorization is deliberately *not* narrowed: the decorated ``POST`` is still
authorized at the write tier, because declaring purity constrains the handler,
never the caller.
"""

from __future__ import annotations

import pathlib
import textwrap
from collections.abc import Iterator

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Field, Session, SQLModel, create_engine

from terp.arch.rules import check_declared_read_only_routes_do_not_write
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
    read_only,
)
from terp.core._internal.session_guard import WriteGuardedSession


class _Draft(BaseTable, table=True):
    __tablename__ = "test_declared_ro_draft"

    text: str = Field(max_length=100)


class _DraftCreate(BaseSchema):
    text: str = Field(max_length=100)


class _DraftUpdate(BaseUpdateSchema):
    text: str | None = None


class _DraftService(BaseService[_Draft, _DraftCreate, _DraftUpdate]):
    model = _Draft


_service = _DraftService()
router = APIRouter(tags=["draft"])


@router.post("/validation", response_model=int)
@read_only
def validate_candidate(session: SessionDep, text: str = "") -> int:
    """The real shape: a POST because the candidate is a body, writing nothing."""
    return len(text) + _service.list(session, skip=0, limit=10)[1]


# NB: deliberately breaks its own promise, to exercise the runtime backstop. It
# lives in arch-exempt test code, never in app/ or a capability.
@router.post("/liar", response_model=str)
@read_only
def liar(session: SessionDep) -> str:
    return str(_service.create(session, _DraftCreate(text="smuggled")).id)


@router.post("/", response_model=str, status_code=201)
def make(session: SessionDep) -> str:
    return str(_service.create(session, _DraftCreate(text="honest")).id)


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
        name="draft",
        router=router,
        policy=Policy.public_write(reason="declared read-only route test"),
    )
    app = create_app([spec])

    def _session_override() -> Iterator[Session]:
        with WriteGuardedSession(engine) as session:
            yield session

    app.dependency_overrides[get_session] = _session_override
    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        SQLModel.metadata.drop_all(engine)
        engine.dispose()


def test_declared_read_only_post_still_serves(client: TestClient) -> None:
    """The point of the feature: a pure POST works exactly as before."""
    assert client.post("/api/v1/draft/validation?text=abc").json() == 3


def test_write_inside_a_declared_read_only_post_fails_closed(
    client: TestClient,
) -> None:
    """The runtime half — the chokepoint refuses it, and nothing persists."""
    assert client.post("/api/v1/draft/liar").status_code == 500
    assert client.get("/api/v1/draft/count").json() == 0


def test_an_undeclared_post_still_writes(client: TestClient) -> None:
    """The guard is opt-in: an ordinary POST is untouched by any of this."""
    assert client.post("/api/v1/draft/").status_code == 201
    assert client.get("/api/v1/draft/count").json() == 1


def _write(tmp_path: pathlib.Path, source: str) -> pathlib.Path:
    app_root = tmp_path / "app"
    (app_root / "modules" / "things").mkdir(parents=True)
    (app_root / "modules" / "things" / "router.py").write_text(
        textwrap.dedent(source), encoding="utf-8"
    )
    return app_root


def test_rule_flags_a_declared_route_that_writes(tmp_path: pathlib.Path) -> None:
    app_root = _write(
        tmp_path,
        """
        from terp.core import read_only

        @router.post("/preview")
        @read_only
        def preview(session, data):
            return service.create(session, data)
        """,
    )
    violations = check_declared_read_only_routes_do_not_write(app_root)
    assert [v.rule for v in violations] == ["declared_read_only_routes_do_not_write"]
    assert "preview" in violations[0].message


def test_rule_accepts_a_declared_route_that_only_reads(tmp_path: pathlib.Path) -> None:
    app_root = _write(
        tmp_path,
        """
        from terp.core import read_only

        @router.post("/preview")
        @read_only
        def preview(session, data):
            return service.list(session, skip=0, limit=10)
        """,
    )
    assert check_declared_read_only_routes_do_not_write(app_root) == []


def test_rule_ignores_an_undeclared_route_that_writes(tmp_path: pathlib.Path) -> None:
    """Only the declaration is this rule's business — ordinary writes are legal."""
    app_root = _write(
        tmp_path,
        """
        @router.post("/things")
        def create_thing(session, data):
            return service.create(session, data)
        """,
    )
    assert check_declared_read_only_routes_do_not_write(app_root) == []


def test_rule_matches_a_qualified_decorator(tmp_path: pathlib.Path) -> None:
    """The import spelling is the author's business, not the rule's."""
    app_root = _write(
        tmp_path,
        """
        from terp import core

        @router.post("/preview")
        @core.read_only
        def preview(session, data):
            return service.update(session, data.id, data)
        """,
    )
    assert len(check_declared_read_only_routes_do_not_write(app_root)) == 1
