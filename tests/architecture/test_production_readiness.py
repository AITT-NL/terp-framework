"""Production-readiness primitives (ADR 0024): health endpoints + engine pool config.

``create_app`` always mounts ``/health/live`` (liveness) and ``/health/ready``
(readiness with a DB ping), and the engine factory applies connection-pool tuning
to a server database while leaving SQLite (dev / test) on its defaults.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from terp.core import ModuleSpec, Policy, create_app, get_session, settings
from terp.core._internal.engine import _engine_options


def _app():
    """A minimal app with one trivial public module; create_app mounts /health."""
    router = APIRouter()

    @router.get("/ping", response_model=str)
    def ping() -> str:
        return "pong"

    return create_app(
        [ModuleSpec(name="demo", router=router, policy=Policy.public(reason="health test"))]
    )


# --- health endpoints -------------------------------------------------------- #
def test_liveness_is_always_up() -> None:
    response = TestClient(_app()).get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_readiness_is_ok_when_the_database_answers() -> None:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    app = _app()

    def _session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = _session
    try:
        response = TestClient(app).get("/health/ready")
        assert response.status_code == 200
        assert response.json() == {"status": "ready", "checks": {"database": "ok"}}
    finally:
        engine.dispose()


def test_readiness_is_503_when_the_database_is_unreachable() -> None:
    app = _app()

    class _BrokenSession:
        def exec(self, *args: object, **kwargs: object) -> object:
            raise RuntimeError("database unreachable")

    def _session() -> Iterator[object]:
        yield _BrokenSession()

    app.dependency_overrides[get_session] = _session
    response = TestClient(app).get("/health/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "checks": {"database": "error"}}


# --- engine connection-pool configuration ------------------------------------ #
def test_sqlite_engine_keeps_default_pool() -> None:
    # SQLite (dev/test) must NOT receive pool_size etc. (and recycling an in-memory
    # connection would discard the database).
    assert _engine_options("sqlite://") == {"echo": False}
    assert _engine_options("sqlite:///./local.db") == {"echo": False}


def test_server_database_applies_the_pool_config() -> None:
    options = _engine_options("postgresql+psycopg://user:pass@db.example/app")
    assert options["pool_size"] == settings.DB_POOL_SIZE
    assert options["max_overflow"] == settings.DB_MAX_OVERFLOW
    assert options["pool_timeout"] == settings.DB_POOL_TIMEOUT
    assert options["pool_recycle"] == settings.DB_POOL_RECYCLE
    assert options["pool_pre_ping"] is settings.DB_POOL_PRE_PING


# --- per-session statement timeout -------------------------------------------- #
def test_postgres_engine_applies_the_statement_timeout() -> None:
    # Every pooled Postgres connection carries `statement_timeout` so one runaway
    # query cannot hold a worker + connection forever.
    options = _engine_options("postgresql+psycopg://user:pass@db.example/app")
    assert options["connect_args"] == {
        "options": f"-c statement_timeout={settings.DB_STATEMENT_TIMEOUT_MS}"
    }


def test_statement_timeout_zero_disables_the_connect_args(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 0 disables the timeout (dev/test only; the production guardrail refuses it).
    monkeypatch.setattr(settings, "DB_STATEMENT_TIMEOUT_MS", 0)
    options = _engine_options("postgresql+psycopg://user:pass@db.example/app")
    assert "connect_args" not in options


def test_non_postgres_server_database_gets_no_statement_timeout_args() -> None:
    # Only Postgres understands `options=-c statement_timeout`; another server DB
    # applies its equivalent knob at the database/DSN level instead.
    options = _engine_options("mysql+pymysql://user:pass@db.example/app")
    assert "connect_args" not in options
    assert _engine_options("sqlite://") == {"echo": False}


# --- per-module schema layout (ADR 0070) -------------------------------------- #
def test_per_module_layout_fails_closed_off_postgres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Schemas are a PostgreSQL feature: any other dialect must fail at engine
    # construction, never open a connection against a layout it cannot express.
    monkeypatch.setattr(settings, "DB_SCHEMA_LAYOUT", "per-module")
    with pytest.raises(RuntimeError, match="per-module"):
        _engine_options("sqlite://")
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        _engine_options("mysql+pymysql://user:pass@db.example/app")
    # …while PostgreSQL keeps its normal options untouched by the layout.
    options = _engine_options("postgresql+psycopg://user:pass@db.example/app")
    assert options["pool_size"] == settings.DB_POOL_SIZE
