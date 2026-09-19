"""The shipped dual-dialect database fixtures (``terp.core.testing``).

ADR 0069 makes two dialects normative — SQLite for development and test, PostgreSQL for
production — and the platform refuses an unverified one at runtime, so an app owner is
told the matrix is real. The executed proof of it was a parametrized fixture in the
framework's own private test tree, in no shipped distribution: the platform's migrations
were held to both dialects while a consumer's, which carry the business schema, could
only ever be held to one. These cover the published fixture's mechanics.

The PostgreSQL scratch-database body is exercised against a recording double rather than
a server. That is not a stand-in for the real lane — the migration conformance suite runs
against a real PostgreSQL in its own CI job — it is coverage of the parts that are logic
rather than SQL: that the yielded URL names the scratch database and not the maintenance
one, and that the drop runs even when the test using it blows up.
"""

from __future__ import annotations

import pathlib
from typing import Any

import pytest
from _pytest.outcomes import Failed, Skipped

import terp.core.db

from terp.core.testing import (
    TERP_POSTGRES_URL_ENV,
    TERP_REQUIRE_POSTGRES_LANE_ENV,
    _postgres_scratch_database,
)


class _RecordingConnection:
    def __init__(self, statements: list[str]) -> None:
        self._statements = statements

    def __enter__(self) -> _RecordingConnection:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def exec_driver_sql(self, statement: str) -> None:
        self._statements.append(statement)


class _RecordingEngine:
    def __init__(self, statements: list[str]) -> None:
        self._statements = statements
        self.disposed = False

    def connect(self) -> _RecordingConnection:
        return _RecordingConnection(self._statements)

    def dispose(self) -> None:
        self.disposed = True


@pytest.fixture
def recorded(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Capture every statement the scratch-database helper would issue."""
    statements: list[str] = []
    engines: list[_RecordingEngine] = []

    def _fake_create_engine(url: str, **kwargs: Any) -> _RecordingEngine:
        engine = _RecordingEngine(statements)
        engines.append(engine)
        return engine

    # Stubbed at `terp.core.db.maintenance_engine`, which is the seam the helper now
    # imports — not at `sqlalchemy.create_engine`. Engine construction moved behind the
    # one `_build` call in `terp.core._internal.engine`, so patching the library function
    # stopped intercepting anything and these tests reached for a real server instead.
    monkeypatch.setattr(terp.core.db, "maintenance_engine", _fake_create_engine)
    monkeypatch.setenv(
        TERP_POSTGRES_URL_ENV, "postgresql+psycopg://user:pw@localhost:5432/postgres"
    )
    statements.append  # keep the reference legible
    return statements


def test_a_maintenance_engine_autocommits_and_pools_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The two properties a server-level statement needs.

    ``CREATE DATABASE`` and ``DROP DATABASE`` cannot run inside a transaction, so the
    engine has to be in AUTOCOMMIT -- the process-wide one is not, which is why this
    second shape exists at all. And it pools nothing, because the caller's next act is
    routinely to drop the very database a pooled connection would still be holding
    open: with a pool, the DROP loses that race and leaves a scratch database behind on
    a server the suite shares with itself.

    Asserted at the construction seam rather than off the built engine, because only one
    of the two is legible afterwards. ``NullPool`` is public on the engine and checked
    that way below; the isolation level is not -- SQLAlchemy keeps it on a private
    dialect attribute and SQLite's connection reports its own emulated level instead, so
    reading it back would either couple this test to a private name or assert the wrong
    thing.
    """
    from sqlalchemy.pool import NullPool

    import terp.core._internal.engine as engine_module

    seen: dict[str, Any] = {}

    def _spy(url: str, **options: Any) -> object:
        seen["url"] = url
        seen.update(options)
        return object()

    monkeypatch.setattr(engine_module, "_build", _spy)
    engine_module.maintenance_engine("postgresql+psycopg://user:pw@example.test/postgres")

    assert seen["isolation_level"] == "AUTOCOMMIT", (
        "CREATE DATABASE cannot run inside a transaction"
    )
    assert seen["poolclass"] is NullPool, (
        "a pooled connection outlives the statement and loses the race with DROP"
    )

    # And the option is one a real engine honours, not just one that is passed along.
    monkeypatch.undo()
    engine = engine_module.maintenance_engine("sqlite://")
    try:
        assert isinstance(engine.pool, NullPool)
    finally:
        engine.dispose()


def test_a_missing_server_skips_rather_than_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """The property that makes this safe to ship to every consumer.

    An offline checkout, a laptop with no database, a fork's first CI run — none of
    them should go red because the platform added a fixture. The lane skips, and the
    skip names the variable that turns it on.
    """
    monkeypatch.delenv(TERP_POSTGRES_URL_ENV, raising=False)
    with pytest.raises(pytest.skip.Exception, match=TERP_POSTGRES_URL_ENV):
        next(_postgres_scratch_database())


def test_a_lane_that_declared_it_runs_this_fails_instead_of_skipping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other half: a skip is green, and a green skip is how a lane stops running.

    The workflow starts a PostgreSQL service and installs a client on purpose, so in
    that context a missing server is not "no database here" — it is one of those steps
    having broken. Left as a skip it is indistinguishable from a pass, and the dialect
    half of a two-dialect matrix quietly stops being tested while every run stays green.

    So the lane says so once, in its own environment, and the fixture believes it. The
    default is unchanged: nothing outside a lane sets this, and the skip above still
    holds for every offline checkout.
    """
    monkeypatch.delenv(TERP_POSTGRES_URL_ENV, raising=False)
    monkeypatch.setenv(TERP_REQUIRE_POSTGRES_LANE_ENV, "1")
    # Catching `Skipped` too, deliberately. A bare `pytest.raises(Failed)` would let a
    # regression here raise `Skipped` straight through the test, and pytest reports that
    # as a SKIP — green, and indistinguishable from a pass. The assertion below is what
    # makes this test fail when the fixture stops honouring the flag, rather than
    # quietly joining the class of silent non-runs it exists to prevent.
    with pytest.raises((Failed, Skipped)) as caught:
        next(_postgres_scratch_database())
    assert isinstance(caught.value, Failed), (
        "with the lane flag set, a missing server must FAIL; a skip is green and says "
        f"nothing, which is the whole reason {TERP_REQUIRE_POSTGRES_LANE_ENV} exists"
    )
    assert TERP_REQUIRE_POSTGRES_LANE_ENV in str(caught.value)


def test_the_scratch_database_is_created_yielded_and_force_dropped(
    recorded: list[str],
) -> None:
    """Each test gets its own database, and the URL it is handed points AT that one.

    Yielding the maintenance URL would be the quiet failure here: everything would work,
    and every test would share one database — so a migration test, whose whole subject is
    what the schema looks like, would be reading the previous test's leftovers as its
    own answer.
    """
    generator = _postgres_scratch_database()
    url = next(generator)

    created = [s for s in recorded if s.startswith("CREATE DATABASE")]
    assert len(created) == 1
    scratch = created[0].split('"')[1]
    assert scratch.startswith("terp_test_")
    assert url.endswith(f"/{scratch}"), "the yielded URL must name the scratch database"
    assert "/postgres" not in url.rsplit("/", 1)[-1]

    with pytest.raises(StopIteration):
        next(generator)
    assert f'DROP DATABASE IF EXISTS "{scratch}" WITH (FORCE)' in recorded, (
        "FORCE because a connection the test disposed may still be closing server-side, "
        "and a drop that loses that race leaves scratch databases behind"
    )


def test_the_database_is_dropped_even_when_the_test_using_it_fails(
    recorded: list[str],
) -> None:
    """Cleanup on the failure path is the half that actually matters.

    A fixture that only tidies up after a passing test leaves one database per failure,
    on the shared server, named after nothing anyone will recognise.
    """
    generator = _postgres_scratch_database()
    next(generator)
    with pytest.raises(RuntimeError, match="the test blew up"):
        generator.throw(RuntimeError("the test blew up"))

    assert any("DROP DATABASE" in statement for statement in recorded), (
        "the failure still propagates — but the database goes away first"
    )


def test_the_sqlite_half_needs_nothing_at_all(tmp_path: pathlib.Path) -> None:
    """The parametrized fixture's first case is a file, so an offline run is complete.

    Exercised through the fixture itself elsewhere in this suite; asserted here as the
    property, because "runs on both" is only true if one of them always runs.
    """
    from terp.core.testing import terp_db_url

    request = type("R", (), {"param": "sqlite"})()
    (url,) = list(terp_db_url.__wrapped__(request, tmp_path))
    assert url.startswith("sqlite:///")
    assert url.endswith("terp-test.db")
