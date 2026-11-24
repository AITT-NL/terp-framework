"""Readiness says when the schema is behind the code (ADR 0221).

A database behind the code answers ``SELECT 1`` like any other, so readiness reported "ready"
over a schema the code's first query then failed on: a bare 500 at sign-in, and nothing
anywhere naming the migration nobody ran. The boot guard refuses that schema, but the template
wires it in production only, and a development stack applies its migrations when it comes up,
not when a running stack's code gains one.

``create_app(migration_readiness=...)`` puts the guard's own question in readiness:

* **what it answers**: 503 with ``migrations: error`` while the check raises, 200 once it
  passes. The check is the boot guard's, so what readiness admits is what the boot admits,
  including a database ahead of the code inside its schema window (ADR 0185);
* **how often it asks**: until it passes once, then never again in the process. Given the
  very object the boot guard ran, it never asks at all, so a production instance pays nothing;
* **what stays as it was**: an app that does not ask has the body it always had.
"""

from __future__ import annotations

import functools
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from terp.core import create_app
from terp.core.health import SCHEMA_CHECK, schema_probe


@pytest.fixture(autouse=True)
def file_database(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:  # type: ignore[no-untyped-def]
    """A file database, as a deployment has, and as the migration guard reads it."""
    from terp.core._internal.engine import reset_engine
    from terp.core.config import settings

    url = f"sqlite:///{tmp_path / 'schema.db'}"
    monkeypatch.setattr(settings, "DATABASE_URL", url)
    reset_engine()
    yield url
    reset_engine()


class _Schema:
    """A migration check standing in for the guard: behind until told it caught up."""

    def __init__(self, *, behind: bool) -> None:
        self.behind = behind
        self.asked = 0
        self.engines: list[Engine] = []

    def __call__(self, engine: Engine) -> None:
        self.asked += 1
        self.engines.append(engine)
        if self.behind:
            raise RuntimeError("1 package(s) are behind their migration head: audit")


def test_a_schema_behind_the_code_is_not_ready_and_says_which_check() -> None:
    schema = _Schema(behind=True)
    client = TestClient(create_app([], migration_readiness=schema))

    behind = client.get("/health/ready")

    assert behind.status_code == 503
    assert behind.json() == {
        "status": "not_ready",
        "checks": {"database": "ok", SCHEMA_CHECK: "error"},
    }
    # Asked with the process engine, the one the app's own sessions use.
    from terp.core.db import get_engine

    assert schema.engines[-1] is get_engine()


def test_readiness_follows_the_schema_once_it_catches_up_and_then_stops_asking() -> None:
    schema = _Schema(behind=True)
    client = TestClient(create_app([], migration_readiness=schema))
    assert client.get("/health/ready").status_code == 503

    schema.behind = False  # the migrate step ran
    caught_up = client.get("/health/ready")
    assert caught_up.status_code == 200
    assert caught_up.json() == {
        "status": "ready",
        "checks": {"database": "ok", SCHEMA_CHECK: "ok"},
    }
    asked = schema.asked

    # A process's code is fixed for its life and a schema does not fall behind by itself,
    # so a passed check is not asked again: a probe every few seconds costs nothing more
    # than it did before this check existed.
    for _ in range(3):
        assert client.get("/health/ready").status_code == 200
    assert schema.asked == asked


def test_the_boot_guard_s_own_pass_counts_and_readiness_never_asks() -> None:
    # The template hands the same object to both seams. A production instance, where the
    # boot guard runs, cannot have started on a behind schema, so readiness has nothing to
    # ask and asks nothing.
    schema = _Schema(behind=False)
    client = TestClient(create_app([], migration_check=schema, migration_readiness=schema))

    ready = client.get("/health/ready")

    assert ready.status_code == 200
    assert ready.json()["checks"][SCHEMA_CHECK] == "ok"
    assert schema.asked == 1, "the boot asked once, and readiness took its answer"


def test_a_different_boot_guard_does_not_answer_for_readiness() -> None:
    # Only the very object counts: a boot guard that asked something else proved nothing
    # about the question readiness was given.
    boot = _Schema(behind=False)
    schema = _Schema(behind=True)
    client = TestClient(create_app([], migration_check=boot, migration_readiness=schema))

    assert client.get("/health/ready").status_code == 503
    assert schema.asked >= 1


def test_an_app_that_does_not_ask_keeps_the_body_it_had() -> None:
    client = TestClient(create_app([]))
    ready = client.get("/health/ready")
    assert ready.status_code == 200
    assert ready.json() == {"status": "ready", "checks": {"database": "ok"}}


def test_the_probe_latches_on_its_first_pass_and_starts_passed_when_told() -> None:
    calls: list[int] = []

    def check() -> None:
        calls.append(1)
        if len(calls) < 2:
            raise RuntimeError("behind")

    probe = schema_probe(check)
    with pytest.raises(RuntimeError):
        probe()
    probe()
    probe()
    assert len(calls) == 2

    untouched: list[int] = []
    schema_probe(lambda: untouched.append(1), passed=True)()
    assert untouched == []


def test_the_migration_guard_itself_turns_readiness_red_then_green(file_database: str) -> None:
    """End to end, with the guard the template wires: a fresh database is behind every
    installed capability's history until it is upgraded, and readiness says so until then."""
    from terp.migrations import assert_migrations_current, orchestrate

    client = TestClient(
        create_app([], migration_readiness=functools.partial(assert_migrations_current))
    )

    behind = client.get("/health/ready")
    assert behind.status_code == 503
    assert behind.json()["checks"] == {"database": "ok", SCHEMA_CHECK: "error"}

    orchestrate.upgrade(file_database, schema_layout="flat")

    assert client.get("/health/ready").status_code == 200
