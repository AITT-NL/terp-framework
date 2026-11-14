"""Phase 7 conformance: install capability -> upgrade -> downgrade across packages.

The dedicated gate the design (§13 Phase 7) asks for, exercised against the real
example app: every table-owning package (the audit / identity / access capabilities
plus the notes / tasks / projects app modules) ships an independent, linear Alembic
history; ``terp migrate upgrade`` creates every table behind its own
``alembic_version_<label>`` table, and ``downgrade`` removes them. Also covers the
fail-closed boot guard, the status view, the ``terp migrate`` CLI, and the
``create_app`` migration-check seam.
"""

from __future__ import annotations

import contextlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import uuid
from collections.abc import Iterator
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.util import CommandError
from sqlalchemy import Engine, create_engine, event, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.pool import NullPool

from terp.core import ModuleSpec, Policy, create_app
from terp.core.migrations import (
    MigrationTree,
    resolve_all_migration_trees,
    resolve_migration_trees,
)
from terp.core.testing import TERP_REQUIRE_POSTGRES_LANE_ENV
from terp.migrations import (
    DatabaseBehindForAutogenerateError,
    MigrationDriftError,
    MigrationError,
    PendingMigrationsError,
    RoleCheck,
    adopt_schemas,
    assert_migrations_current,
    assert_migrations_match_models,
    assert_migrations_reverse_cleanly,
    check_roles,
    downgrade,
    grant_runtime_role,
    migration_status,
    stamp,
    upgrade,
    upgrade_sql,
)
from terp.migrations import cli as migrate_cli
from terp.migrations import orchestrate
from terp.migrations._config import alembic_config_for
from terp.migrations.cli import migrate_main

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
APP_ROOT = _REPO_ROOT / "apps" / "example" / "app"

_EXPECTED_LABELS = ["access", "audit", "files", "groups", "identity", "leases", "mfa", "outbox", "sync", "webhooks", "journals", "notes", "projects", "tasks"]
_DOMAIN_TABLES = {
    "access_grant",
    "audit_event",
    "file_object",
    "identity_user",
    "identity_federated_identity",
    "journal",
    "note",
    "outbox_message",
    "resource_lease",
    "project",
    "sync_mapping",
    "sync_run",
    "sync_record_log",
    "task",
    "user_group",
    "user_group_member",
    "webhook_subscription",
    "webhook_delivery",
}


@pytest.fixture
def db_url(terp_db_url: str) -> str:
    """Every conformance test runs on SQLite and on the verified production dialect.

    This is now the SHIPPED fixture (``terp_db_url``, from ``terp.core.testing``) under
    the local name these tests already use. It used to be a private copy living here,
    which meant the platform proved its own migrations on both dialects while a
    consumer's — the ones carrying the business schema — could only ever be proven on
    SQLite. Consuming the published fixture rather than a copy of it is what keeps the
    two from drifting: if the shipped one breaks, this suite is what says so.

    The PostgreSQL lane (ADR 0069) runs when ``TERP_TEST_POSTGRES_URL`` points at a
    server (CI provides one; locally the lane skips). SQLite alone would keep masking
    real differences — VARCHAR length enforcement, timezone-aware datetimes, native
    ALTER vs batch mode — so the migration subsystem must hold on both.
    """
    return terp_db_url


@pytest.fixture
def pg_url(terp_pg_url: str) -> str:
    """A PostgreSQL-only scratch database (the per-module layout is PG-only)."""
    return terp_pg_url


def _table_names(url: str) -> set[str]:
    engine = create_engine(url)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_upgrade_creates_every_table_then_downgrade_removes_them(db_url: str) -> None:
    applied = upgrade(db_url, APP_ROOT, package="app")
    assert applied == _EXPECTED_LABELS

    names = _table_names(db_url)
    assert _DOMAIN_TABLES <= names
    # each package's history is isolated in its own version table
    assert {f"alembic_version_{label}" for label in _EXPECTED_LABELS} <= names

    reverted = downgrade(db_url, APP_ROOT, package="app")
    assert reverted == list(reversed(_EXPECTED_LABELS))
    assert _DOMAIN_TABLES.isdisjoint(_table_names(db_url))


def test_the_whole_history_reverses_cleanly_on_both_dialects(db_url: str) -> None:
    """The reverse direction, executed rather than read.

    The test above walks down and back once and checks the domain tables are gone. This
    is the shipped helper a consumer runs on its own history, pointed at the platform's
    thirteen — so the thing an app is told to rely on is proven here first, on both
    verified dialects, where the two fail differently: SQLite exercises batch mode, and
    PostgreSQL exercises native ALTER and the constraint names a server will accept.
    """
    assert_migrations_reverse_cleanly(db_url, APP_ROOT, package="app")


def test_audit_trail_is_append_only_at_the_database(db_url: str) -> None:
    """ADR 0076: the database itself refuses an UPDATE/DELETE on ``audit_event``.

    The service layer never exposed one, but that was convention; the migration's
    row-level triggers make even a raw connection on the app role unable to rewrite
    history — proven here below the ORM, on both gate dialects.
    """
    upgrade(db_url, APP_ROOT, package="app")
    engine = create_engine(db_url)
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO audit_event (id, action, target_type, target_id, created_at)"
                    " VALUES (:id, 'created', 'note', :target, '2026-01-01 00:00:00+00')"
                ),
                {"id": str(uuid.uuid4()), "target": str(uuid.uuid4())},
            )
        with pytest.raises(DBAPIError, match="append-only"):
            with engine.begin() as conn:
                conn.exec_driver_sql("UPDATE audit_event SET action = 'updated'")
        with pytest.raises(DBAPIError, match="append-only"):
            with engine.begin() as conn:
                conn.exec_driver_sql("DELETE FROM audit_event")
        with engine.connect() as conn:
            count = conn.exec_driver_sql("SELECT COUNT(*) FROM audit_event").scalar_one()
            action = conn.exec_driver_sql("SELECT action FROM audit_event").scalar_one()
        assert count == 1  # the row survived both attempts…
        assert action == "created"  # …unmodified
    finally:
        engine.dispose()


def test_guard_fails_closed_when_behind_and_passes_when_current(db_url: str) -> None:
    engine = create_engine(db_url)
    try:
        with pytest.raises(PendingMigrationsError) as excinfo:
            assert_migrations_current(engine, APP_ROOT, package="app")
        assert set(excinfo.value.behind) == set(_EXPECTED_LABELS)
    finally:
        engine.dispose()

    upgrade(db_url, APP_ROOT, package="app")

    engine = create_engine(db_url)
    try:
        assert_migrations_current(engine, APP_ROOT, package="app")  # no raise
    finally:
        engine.dispose()


def test_committed_migrations_match_the_models(db_url: str) -> None:
    """No drift: autogenerate finds nothing after upgrade (migrations == models).

    The build-time pair to the runtime boot guard — a changed model with no
    regenerated migration is caught here, not in production.
    """
    upgrade(db_url, APP_ROOT, package="app")
    for tree in resolve_migration_trees(APP_ROOT, package="app"):
        command.check(alembic_config_for(tree, db_url))  # raises on any pending diff


def test_status_reports_each_package_at_head_after_upgrade(db_url: str) -> None:
    upgrade(db_url, APP_ROOT, package="app")
    engine = create_engine(db_url)
    try:
        rows = migration_status(engine, APP_ROOT, package="app")
    finally:
        engine.dispose()
    by_label = {row.label: row for row in rows}
    assert set(by_label) == set(_EXPECTED_LABELS)
    assert all(row.is_current for row in rows)
    assert by_label["audit"].current == by_label["audit"].head


def test_cli_upgrade_status_check_and_downgrade(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    common = ["--database-url", db_url, "--app-root", str(APP_ROOT)]

    migrate_main(["upgrade", *common])
    assert "upgraded:" in capsys.readouterr().out
    assert _DOMAIN_TABLES <= _table_names(db_url)

    migrate_main(["status", *common])
    status_out = capsys.readouterr().out
    assert "audit" in status_out and "ok" in status_out

    migrate_main(["check", *common])
    assert "migrations current" in capsys.readouterr().out

    migrate_main(["downgrade", *common])
    assert "downgraded:" in capsys.readouterr().out
    assert _DOMAIN_TABLES.isdisjoint(_table_names(db_url))


def test_cli_prints_an_unreadable_history_as_its_answer(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A revision past the Windows path limit reaches the operator as the fix, not a traceback."""
    import terp.migrations.cli as migrate_cli
    from terp.core.migrations import MigrationDiscoveryError

    def unreadable(*_args: object, **_kwargs: object) -> list[str]:
        raise MigrationDiscoveryError("the 'identity' migration history lists 4f1c… but its path is 318 characters")

    monkeypatch.setattr(migrate_cli, "upgrade", unreadable)
    with pytest.raises(SystemExit) as excinfo:
        migrate_main(
            ["upgrade", "--database-url", f"sqlite:///{tmp_path / 'x.db'}", "--app-root", str(APP_ROOT)]
        )
    assert excinfo.value.code == 2
    assert "its path is 318 characters" in capsys.readouterr().err


def test_cli_check_exits_nonzero_when_behind(tmp_path: pathlib.Path) -> None:
    fresh = f"sqlite:///{tmp_path / 'fresh.db'}"
    with pytest.raises(SystemExit) as excinfo:
        migrate_main(["check", "--database-url", fresh, "--app-root", str(APP_ROOT)])
    assert excinfo.value.code == 1


def test_cli_make_dispatches_without_app_root(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from terp.core.migrations import MigrationTree

    fake = MigrationTree("widgets", "app.modules.widgets", tmp_path / "migrations")
    monkeypatch.setattr(migrate_cli, "make", lambda *a, **k: fake)
    # No --app-root: resolves to ./app which is absent here -> app_root None branch.
    # --no-autogenerate: without it `make` needs a live database, so the in-memory URL
    # is refused before dispatch ever happens (which is the point of this file's
    # in-memory tests further down).
    migrate_main(
        ["make", "widgets", "-m", "create widgets", "--no-autogenerate", "--database-url", "sqlite://"]
    )
    assert "widgets" in capsys.readouterr().out


def test_cli_make_message_defaults_to_label(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from terp.core.migrations import MigrationTree

    fake = MigrationTree("widgets", "app.modules.widgets", tmp_path / "migrations")
    seen: dict[str, object] = {}

    def _fake_make(label: str, message: str, *a: object, **k: object) -> MigrationTree:
        seen["message"] = message
        return fake

    monkeypatch.setattr(migrate_cli, "make", _fake_make)
    # No -m: the message defaults to a label-derived one (`terp migrate make <label>`).
    migrate_main(["make", "widgets", "--no-autogenerate", "--database-url", "sqlite://"])
    assert seen["message"] == "update widgets"
    assert "widgets" in capsys.readouterr().out


def test_create_app_runs_migration_check_when_supplied(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = object()
    monkeypatch.setattr("terp.core.app.get_engine", lambda: sentinel)
    seen: dict[str, object] = {}
    spec = ModuleSpec(name="probe", policy=Policy.public(reason="probe"))

    create_app([spec], migration_check=lambda engine: seen.__setitem__("engine", engine))

    assert seen["engine"] is sentinel


def _strip_version_tables(db_url: str) -> None:
    """Simulate a brownfield DB: real schema present, no alembic_version_* tables."""
    engine = create_engine(db_url)
    try:
        with engine.begin() as conn:
            for label in _EXPECTED_LABELS:
                conn.exec_driver_sql(f"DROP TABLE alembic_version_{label}")
        remaining = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    assert not any(name.startswith("alembic_version") for name in remaining)


def test_stamp_baselines_an_existing_schema_without_dropping_data(db_url: str) -> None:
    upgrade(db_url, APP_ROOT, package="app")
    _strip_version_tables(db_url)  # an existing DB Terp did not create the version tables for

    assert stamp(db_url, APP_ROOT, package="app") == _EXPECTED_LABELS

    engine = create_engine(db_url)
    try:
        assert_migrations_current(engine, APP_ROOT, package="app")  # adopted, nothing pending
        names = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    assert _DOMAIN_TABLES <= names  # the data schema was preserved, not recreated
    assert {f"alembic_version_{label}" for label in _EXPECTED_LABELS} <= names


def test_guard_with_app_root_flags_app_modules_behind(db_url: str) -> None:
    # Upgrade ONLY the capabilities; the app's own modules are left un-migrated.
    for tree in resolve_migration_trees(None):
        command.upgrade(alembic_config_for(tree, db_url), "head")

    engine = create_engine(db_url)
    try:
        with pytest.raises(PendingMigrationsError) as excinfo:
            assert_migrations_current(engine, APP_ROOT, package="app")
        # the app modules (not just caps) are reported behind
        assert set(excinfo.value.behind) == {"notes", "tasks", "projects", "journals"}
    finally:
        engine.dispose()


def test_downgrade_with_label_targets_only_one_package(db_url: str) -> None:
    upgrade(db_url, APP_ROOT, package="app")
    reverted = downgrade(db_url, APP_ROOT, package="app", revision="base", label="audit")
    assert reverted == ["audit"]
    names = _table_names(db_url)
    assert "audit_event" not in names  # only audit was rolled back
    assert {"note", "task", "project"} <= names  # the other packages are untouched


def test_assert_migrations_match_models_passes_after_upgrade(db_url: str) -> None:
    upgrade(db_url, APP_ROOT, package="app")
    assert_migrations_match_models(db_url, APP_ROOT, package="app")  # no raise


def test_assert_migrations_match_models_detects_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    from alembic.util import CommandError

    from terp.migrations import guard as guard_mod

    def _pretend_drift(_config: object) -> None:
        raise CommandError("pretend the model changed")

    monkeypatch.setattr(guard_mod.command, "check", _pretend_drift)
    with pytest.raises(MigrationDriftError) as excinfo:
        assert_migrations_match_models("sqlite://", package="app")
    assert excinfo.value.drifted  # the drifted package label(s) are named


def test_cli_stamp_then_check(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    common = ["--database-url", db_url, "--app-root", str(APP_ROOT)]
    upgrade(db_url, APP_ROOT, package="app")
    _strip_version_tables(db_url)

    migrate_main(["stamp", *common])
    assert "stamped:" in capsys.readouterr().out
    migrate_main(["check", *common])
    assert "migrations current" in capsys.readouterr().out


def test_cli_heads_reports_a_single_head(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    migrate_main(["heads", "--database-url", db_url, "--app-root", str(APP_ROOT)])
    out = capsys.readouterr().out
    assert "audit" in out and "ok" in out



def test_cli_graph_prints_the_histories_alembic_loads(capsys: pytest.CaptureFixture[str]) -> None:
    # The default in-memory database: graph opens none, so it is never refused for one.
    migrate_main(["graph", "--app-root", str(APP_ROOT)])
    loaded = json.loads(capsys.readouterr().out)
    assert set(loaded) == {tree.label for tree in resolve_migration_trees(APP_ROOT)}, (
        "one entry per history with a revision file, and no other"
    )
    assert loaded["audit"], "a capability's history is read as Alembic loads it"
    for revisions in loaded.values():
        bases = [revision for revision, parents in revisions.items() if parents == []]
        assert bases, "every history Alembic loads has a base"
        assert all(parent in revisions for parents in revisions.values() for parent in parents)


def test_cli_graph_refuses_a_history_it_cannot_load(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def unloadable(*_args: object, **_kwargs: object) -> dict[str, dict[str, list[str]]]:
        raise MigrationError("the audit migration history names the parent revision 'x'")

    monkeypatch.setattr(migrate_cli, "graph", unloadable)
    with pytest.raises(SystemExit) as exited:
        migrate_main(["graph", "--database-url", "sqlite://"])
    assert exited.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "names the parent revision 'x'" in captured.err

def test_cli_downgrade_with_label(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    common = ["--database-url", db_url, "--app-root", str(APP_ROOT)]
    migrate_main(["upgrade", *common])
    capsys.readouterr()
    migrate_main(["downgrade", "--label", "audit", "--revision", "base", *common])
    assert "downgraded: ['audit']" in capsys.readouterr().out


def test_cli_merge_dispatches(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from terp.core.migrations import MigrationTree

    fake = MigrationTree("audit", "terp.capabilities.audit", tmp_path / "migrations")
    monkeypatch.setattr(migrate_cli, "merge_heads", lambda *a, **k: fake)
    migrate_main(["merge", "audit", "-m", "merge heads", "--database-url", "sqlite://"])
    assert "merged heads for audit" in capsys.readouterr().out


def test_cli_explicit_bad_app_root_fails_closed(tmp_path: pathlib.Path) -> None:
    # An explicit --app-root that is not a directory must fail closed (non-zero exit),
    # never silently degrade to checking installed capabilities only (so a typo cannot
    # skip every app module and falsely report "migrations current").
    missing = tmp_path / "typo-app"
    with pytest.raises(SystemExit) as excinfo:
        migrate_main(
            [
                "check",
                "--database-url",
                f"sqlite:///{tmp_path / 'a.db'}",
                "--app-root",
                str(missing),
            ]
        )
    assert excinfo.value.code == 2


# --------------------------------------------------------------------------- #
# per-module schema layout (ADR 0070) — PostgreSQL-only, env-gated like the lane.
# --------------------------------------------------------------------------- #
def _schema_tables(url: str, schema: str) -> set[str]:
    engine = create_engine(url)
    try:
        return set(inspect(engine).get_table_names(schema=schema))
    finally:
        engine.dispose()


def test_per_module_layout_places_each_package_in_its_own_schema(pg_url: str) -> None:
    applied = upgrade(pg_url, APP_ROOT, package="app", schema_layout="per-module")
    assert applied == _EXPECTED_LABELS

    # Tables live in their package's schema; nothing domain-shaped stays in public.
    assert "note" in _schema_tables(pg_url, "notes")
    assert "audit_event" in _schema_tables(pg_url, "audit")
    public = _schema_tables(pg_url, "public")
    assert _DOMAIN_TABLES.isdisjoint(public)
    # …while every version table stays pinned to public (status stays layout-unaware).
    assert {f"alembic_version_{label}" for label in _EXPECTED_LABELS} <= public

    # The database-level search_path routes a *plain* connection (the app engine,
    # psql, a BI tool): unqualified names resolve with zero layout knowledge.
    engine = create_engine(pg_url)
    try:
        with engine.connect() as conn:
            assert conn.exec_driver_sql("SELECT COUNT(*) FROM note").scalar() == 0
    finally:
        engine.dispose()

    # The boot guard and status read through the same plain engine, layout-unaware.
    engine = create_engine(pg_url)
    try:
        assert_migrations_current(engine, APP_ROOT, package="app")
    finally:
        engine.dispose()


def test_per_module_layout_survives_the_drift_check(pg_url: str) -> None:
    # The fiddly corner the ADR flags: autogenerate/command.check must stay meaningful
    # under the search_path recipe — committed revisions == models, per schema.
    upgrade(pg_url, APP_ROOT, package="app", schema_layout="per-module")
    assert_migrations_match_models(
        pg_url, APP_ROOT, package="app", schema_layout="per-module"
    )  # no raise


def test_per_module_layout_downgrade_removes_every_table(pg_url: str) -> None:
    upgrade(pg_url, APP_ROOT, package="app", schema_layout="per-module")
    reverted = downgrade(pg_url, APP_ROOT, package="app", schema_layout="per-module")
    assert reverted == list(reversed(_EXPECTED_LABELS))
    assert _schema_tables(pg_url, "notes") == set()
    assert _schema_tables(pg_url, "audit") == set()


def test_adopt_schemas_moves_a_flat_database_in_place(pg_url: str) -> None:
    # Brownfield: a database built flat adopts the layout without recreating a table.
    upgrade(pg_url, APP_ROOT, package="app")  # flat
    assert "note" in _schema_tables(pg_url, "public")

    moved = adopt_schemas(pg_url, APP_ROOT, package="app")
    assert "note" in moved["notes"]
    assert "note" in _schema_tables(pg_url, "notes")
    assert "note" not in _schema_tables(pg_url, "public")
    # Version tables stayed put — the histories still read as current…
    engine = create_engine(pg_url)
    try:
        assert_migrations_current(engine, APP_ROOT, package="app")
        with engine.connect() as conn:
            assert conn.exec_driver_sql("SELECT COUNT(*) FROM note").scalar() == 0
    finally:
        engine.dispose()
    # …and adopting again is a no-op (idempotent).
    assert adopt_schemas(pg_url, APP_ROOT, package="app") == {}


def test_adopt_schemas_rolls_back_wholesale_on_failure(pg_url: str) -> None:
    # All-or-nothing: a mid-run failure must not leave the database half-adopted.
    # A conflicting table pre-created in the `notes` schema makes the `note` move
    # fail — every move (including packages adopted before it) must roll back.
    upgrade(pg_url, APP_ROOT, package="app")  # flat
    engine = create_engine(pg_url, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql('CREATE SCHEMA IF NOT EXISTS "notes"')
            conn.exec_driver_sql('CREATE TABLE "notes"."note" (id integer)')
    finally:
        engine.dispose()

    with pytest.raises(Exception):  # the driver's error class is incidental
        adopt_schemas(pg_url, APP_ROOT, package="app")

    # Nothing moved: the tables adopted before the failing one are back in public.
    public = _schema_tables(pg_url, "public")
    assert "note" in public
    assert "audit_event" in public  # audit sorts before notes, so it had already "moved"
    assert _schema_tables(pg_url, "audit") == set()


def test_cli_adopt_schemas_reports_the_moves(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        migrate_cli, "adopt_schemas", lambda *a, **k: {"notes": ["note"]}
    )
    migrate_main(["adopt-schemas", "--database-url", "postgresql://u:p@h/db"])
    out = capsys.readouterr().out
    assert "notes" in out and "adopted:" in out


def test_cli_adopt_schemas_fails_closed_off_postgres(
    capsys: pytest.CaptureFixture[str], tmp_path: pathlib.Path
) -> None:
    """A real (file) SQLite URL: the refusal under test is "not PostgreSQL", not
    "in-memory" — those are two different failures and each gets its own test."""
    with pytest.raises(SystemExit) as excinfo:
        migrate_main(["adopt-schemas", "--database-url", f"sqlite:///{tmp_path / 'a.db'}"])
    assert excinfo.value.code == 1
    assert "PostgreSQL" in capsys.readouterr().err


def test_cli_refuses_an_in_memory_database_for_a_stateful_command(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``upgrade`` against ``sqlite://`` used to succeed and be discarded on exit.

    It printed ``upgraded: [...]`` while ``check``, one line later in the same shell,
    reported the app behind its code. Both were true; the pair was misleading.
    """
    with pytest.raises(SystemExit) as excinfo:
        migrate_main(["upgrade", "--database-url", "sqlite://"])
    assert excinfo.value.code == 2
    assert "in-memory" in capsys.readouterr().err


def test_cli_refuses_an_in_memory_database_for_check_too(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The other half of the misleading pair — the same refusal, not a "behind" report."""
    with pytest.raises(SystemExit) as excinfo:
        migrate_main(["check", "--database-url", "sqlite:///:memory:"])
    assert excinfo.value.code == 2
    assert "in-memory" in capsys.readouterr().err


def test_cli_refuses_the_shared_cache_spelling_of_in_memory(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``?mode=memory`` is the same database with a different spelling."""
    with pytest.raises(SystemExit) as excinfo:
        migrate_main(["status", "--database-url", "sqlite:///x?mode=memory"])
    assert excinfo.value.code == 2


def test_cli_in_memory_refusal_names_the_setting_it_came_from(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Falling back to the settings default is the common case — name DATABASE_URL, not
    the flag the developer never passed."""
    monkeypatch.setattr(
        migrate_cli, "get_settings", lambda: SimpleNamespace(DATABASE_URL="sqlite://")
    )
    with pytest.raises(SystemExit):
        migrate_main(["upgrade"])
    assert "DATABASE_URL points at" in capsys.readouterr().err


def test_cli_in_memory_refusal_for_make_prints_the_working_command(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Every module author meets this once per module — so ``make`` gives the answer.

    Diagnosis alone ("that database dies with the process") leaves the author to
    invent the throwaway-file recipe themselves. The refusal names the label they
    passed and the two commands that work.
    """
    with pytest.raises(SystemExit) as excinfo:
        migrate_main(["make", "widgets", "--database-url", "sqlite://"])
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "terp migrate upgrade" in err
    assert "terp migrate make widgets" in err
    assert "--no-autogenerate" in err


def test_database_behind_for_autogenerate_names_both_commands_against_this_url() -> None:
    """The second wall in a row must not be answered with a third prompt.

    The in-memory refusal sends the author to a file database, which is then empty
    and therefore behind head. If this error only diagnosed, they would meet
    ``terp migrate status``, then ``upgrade``, then ``make`` — three round trips for
    one intent. It leads with the two commands that satisfy both walls, pointed at
    the database the author is already using.
    """
    from terp.migrations.errors import DatabaseBehindForAutogenerateError

    message = str(
        DatabaseBehindForAutogenerateError("widgets", "sqlite:///./.migrate-scratch.db")
    )
    assert 'DATABASE_URL="sqlite:///./.migrate-scratch.db" terp migrate upgrade' in message
    assert (
        'DATABASE_URL="sqlite:///./.migrate-scratch.db" terp migrate make widgets' in message
    )
    assert "$env:DATABASE_URL" in message  # the PowerShell spelling, not left as an exercise
    assert "--no-autogenerate" in message


def test_cli_allows_an_in_memory_database_for_a_script_tree_command(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``make --no-autogenerate`` / ``merge`` / ``heads`` / ``upgrade --sql`` work on
    files, not on state.

    Refusing them would cost a developer with no database configured the one half of
    the CLI that never needed one. Autogenerating ``make`` is the exception and is
    covered below: it diffs the live database, so it is stateful in every sense that
    matters to the author.
    """
    monkeypatch.setattr(
        migrate_cli,
        "upgrade_sql",
        lambda *a, **k: "-- ddl\n",
    )
    migrate_main(["upgrade", "--sql", "--database-url", "sqlite://"])
    assert "-- ddl" in capsys.readouterr().out


def test_cli_refuses_an_in_memory_database_for_autogenerating_make(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The first command a new module author runs must not answer in raw Alembic.

    ``terp new module x`` then ``terp migrate make x`` is the documented workflow, and
    on the settings default (in-memory SQLite) it used to fail in a 25-line Alembic
    traceback ending in "Target database is not up to date." — which names neither the
    cause nor the fix, and never mentions DATABASE_URL. ``make`` was classified as a
    script-tree command because *authoring* a revision is one; autogenerating it is not.
    """
    with pytest.raises(SystemExit) as excinfo:
        migrate_main(["make", "widgets", "--database-url", "sqlite://"])
    assert excinfo.value.code == 2
    assert "in-memory" in capsys.readouterr().err


def test_cli_still_authors_a_revision_by_hand_without_a_database(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The refusal above is scoped to the diff, not to the command.

    ``--no-autogenerate`` writes an empty revision from the script tree alone, so the
    escape the error message offers has to actually work with no database configured.
    """
    from terp.core.migrations import MigrationTree

    fake = MigrationTree("widgets", "app.modules.widgets", tmp_path / "migrations")
    monkeypatch.setattr(migrate_cli, "make", lambda *a, **k: fake)
    migrate_main(["make", "widgets", "--no-autogenerate", "--database-url", "sqlite://"])
    assert "widgets" in capsys.readouterr().out


def test_make_translates_alembics_out_of_date_refusal_into_the_fix(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A real (file-backed) database that is merely behind gets a directive message.

    The in-memory refusal covers the unconfigured case; this covers the configured one,
    where Alembic's own ``CommandError`` is correct but unreadable. The CLI must print
    the typed error and stop, not re-raise a traceback the author has to read Alembic
    to interpret — and the message must name the command that fixes it.
    """

    def _raise(*a: object, **k: object) -> None:
        raise DatabaseBehindForAutogenerateError("widgets", "sqlite:///app.db")

    monkeypatch.setattr(migrate_cli, "make", _raise)
    db = f"sqlite:///{tmp_path / 'app.db'}"
    with pytest.raises(SystemExit) as excinfo:
        migrate_main(["make", "widgets", "--database-url", db])
    assert excinfo.value.code == 1
    err = capsys.readouterr().err
    assert "terp migrate upgrade" in err
    assert "DATABASE_URL" in err
    assert "--no-autogenerate" in err


def test_make_raises_the_typed_error_from_the_orchestrator_itself(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The translation lives in ``make``, not in the CLI, so the API half gets it too.

    An app calling ``terp.migrations.make`` directly (Studio does) would otherwise still
    surface the raw Alembic error to its user.
    """

    def _raise(*a: object, **k: object) -> None:
        raise CommandError("Target database is not up to date.")

    monkeypatch.setattr(orchestrate.command, "revision", _raise)
    monkeypatch.setattr(
        orchestrate,
        "resolve_migration_target",
        lambda *a, **k: MigrationTree("widgets", "app.modules.widgets", tmp_path / "m"),
    )
    monkeypatch.setattr(orchestrate, "assert_no_homeless_tables", lambda *a, **k: None)
    monkeypatch.setattr(orchestrate, "assert_no_split_table_ownership", lambda *a, **k: None)

    with pytest.raises(DatabaseBehindForAutogenerateError) as excinfo:
        orchestrate.make("widgets", "m", f"sqlite:///{tmp_path / 'app.db'}")
    assert "terp migrate upgrade" in str(excinfo.value)
    # The failed-make cleanup still ran: no empty versions/ left to be mistaken for
    # an (empty, falsely "current") runnable history.
    assert not (tmp_path / "m").exists()


def test_make_leaves_every_other_alembic_error_alone(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only the one condition with a known fix is translated.

    Swallowing the rest into a friendlier wrapper would trade a readable Alembic error
    for a vaguer Terp one, which is the opposite of the point.
    """

    def _raise(*a: object, **k: object) -> None:
        raise CommandError("No such revision or branch 'nope'")

    monkeypatch.setattr(orchestrate.command, "revision", _raise)
    monkeypatch.setattr(
        orchestrate,
        "resolve_migration_target",
        lambda *a, **k: MigrationTree("widgets", "app.modules.widgets", tmp_path / "m"),
    )
    monkeypatch.setattr(orchestrate, "assert_no_homeless_tables", lambda *a, **k: None)
    monkeypatch.setattr(orchestrate, "assert_no_split_table_ownership", lambda *a, **k: None)

    with pytest.raises(CommandError, match="No such revision"):
        orchestrate.make("widgets", "m", f"sqlite:///{tmp_path / 'app.db'}")
    assert not (tmp_path / "m").exists()


# --------------------------------------------------------------------------- #
# offline SQL rendering (ADR 0072) — DBA-reviewable scripts, nothing connects.
# --------------------------------------------------------------------------- #
def test_upgrade_sql_renders_an_offline_script_without_touching_the_database() -> None:
    # A PostgreSQL URL at a nonexistent host: offline mode needs only the dialect,
    # so success is itself the proof that no connection was ever attempted. (SQLite
    # is not the offline target — its ALTERs need batch mode, which Alembic cannot
    # render offline; the DBA use case is the server dialect, ADR 0072.)
    script = upgrade_sql(
        "postgresql+psycopg://user:pw@host.invalid/appdb", APP_ROOT, package="app"
    )
    # Real DDL for every package, in the same dependency order upgrade applies…
    assert "CREATE TABLE" in script
    assert "-- terp migrate: audit" in script
    assert "-- terp migrate: notes" in script
    # …including the version-table bookkeeping, so a DBA-applied database still
    # reports current to `terp migrate status` and the boot guard.
    assert "alembic_version_notes" in script


def test_upgrade_sql_refuses_the_per_module_layout() -> None:
    with pytest.raises(MigrationError, match="flat layout only"):
        upgrade_sql(
            "postgresql://u:p@h/db", APP_ROOT, package="app", schema_layout="per-module"
        )


def test_cli_upgrade_sql_prints_the_script(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(migrate_cli, "upgrade_sql", lambda *a, **k: "-- SQL SCRIPT\n")
    migrate_main(["upgrade", "--sql", "--database-url", "sqlite://"])
    assert "-- SQL SCRIPT" in capsys.readouterr().out


def test_cli_upgrade_sql_fails_closed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def _refuse(*args: object, **kwargs: object) -> str:
        raise MigrationError("offline SQL (--sql) supports the flat layout only")

    monkeypatch.setattr(migrate_cli, "upgrade_sql", _refuse)
    with pytest.raises(SystemExit) as excinfo:
        migrate_main(["upgrade", "--sql", "--database-url", "postgresql://u:p@h/db"])
    assert excinfo.value.code == 1
    assert "flat layout only" in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# runtime role grants (ADR 0071) — the database itself refuses cross-privilege
# operations under the app's login. PostgreSQL-only, env-gated like the lane.
# --------------------------------------------------------------------------- #
def test_runtime_role_gets_dml_and_is_refused_ddl_and_tampering(pg_url: str) -> None:
    from sqlalchemy.exc import ProgrammingError

    upgrade(pg_url, APP_ROOT, package="app", schema_layout="per-module")

    role = f"terp_rt_{uuid.uuid4().hex[:10]}"
    admin = create_engine(pg_url, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    try:
        with admin.connect() as conn:
            conn.exec_driver_sql(f"CREATE ROLE \"{role}\" LOGIN PASSWORD 'rt-secret'")
        # owner_role names the migration owner (the scratch DB's admin login here),
        # live-validating the ALTER DEFAULT PRIVILEGES FOR ROLE shape end-to-end.
        grant_runtime_role(
            pg_url,
            role,
            APP_ROOT,
            package="app",
            schema_layout="per-module",
            owner_role=make_url(pg_url).username,
        )

        runtime_url = (
            make_url(pg_url)
            .set(username=role, password="rt-secret")
            .render_as_string(hide_password=False)
        )
        runtime = create_engine(runtime_url, poolclass=NullPool)
        try:
            with runtime.connect() as conn:
                # DML the audited service layer needs: zero-row probes exercise the
                # privilege without needing any data.
                assert conn.exec_driver_sql("SELECT COUNT(*) FROM note").scalar() == 0
                conn.exec_driver_sql("INSERT INTO note SELECT * FROM note WHERE 1=0")
                conn.exec_driver_sql("UPDATE note SET title = title WHERE 1=0")
                conn.exec_driver_sql("DELETE FROM note WHERE 1=0")
                # The boot guard's read of migration state still works…
                assert (
                    conn.exec_driver_sql(
                        "SELECT COUNT(*) FROM public.alembic_version_notes"
                    ).scalar()
                    == 1
                )
                # …and cross-MODULE DML is deliberately ALLOWED (pinned so the
                # boundary is never misread): one runtime role spans every write
                # schema because audit/outbox rows ride the business write's single
                # session (ADR 0071 corollary; module isolation stays code-enforced).
                conn.exec_driver_sql(
                    "INSERT INTO audit.audit_event "
                    "SELECT * FROM audit.audit_event WHERE 1=0"
                )
                conn.commit()
            # …but the DATABASE refuses DDL: no create, no drop, no alter.
            for refused in (
                "CREATE TABLE notes.evil (id int)",
                "DROP TABLE notes.note",
                "ALTER TABLE notes.note ADD COLUMN evil int",
                # …and refuses tampering with migration state (public is read-only),
                # the schema window's record included (ADR 0185): it takes exactly the
                # version tables' grants.
                "DELETE FROM public.alembic_version_notes WHERE 1=0",
                "INSERT INTO public.terp_migration_window"
                " SELECT * FROM public.terp_migration_window WHERE 1=0",
                "UPDATE public.terp_migration_window SET kind = 'expand' WHERE 1=0",
                "DELETE FROM public.terp_migration_window WHERE 1=0",
            ):
                with runtime.connect() as conn, pytest.raises(ProgrammingError):
                    conn.exec_driver_sql(refused)
        finally:
            runtime.dispose()
    finally:
        # Roles are cluster-wide: revoke everything granted in this scratch database,
        # then drop the login, regardless of assertion outcome.
        with admin.connect() as conn:
            conn.exec_driver_sql(f'DROP OWNED BY "{role}"')
            conn.exec_driver_sql(f'DROP ROLE "{role}"')
        admin.dispose()


# What grant-runtime takes from PUBLIC (ADR 0071, amended 2026-11-14): EXECUTE on every
# function, procedure, aggregate and window function in the app's schemas, by name for
# those that exist and as the owner's global default for those made later.
@contextlib.contextmanager
def _login(pg_url: str, prefix: str) -> Iterator[tuple[str, str]]:
    """A throwaway login and its URL on *pg_url*'s database, dropped with all it holds after."""
    role = f"{prefix}_{uuid.uuid4().hex[:10]}"
    admin = create_engine(pg_url, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    try:
        with admin.connect() as conn:
            conn.exec_driver_sql(f"CREATE ROLE \"{role}\" LOGIN PASSWORD 'rt-secret'")
        yield role, make_url(pg_url).set(username=role, password="rt-secret").render_as_string(
            hide_password=False
        )
    finally:
        with admin.connect() as conn:
            conn.exec_driver_sql(f'DROP OWNED BY "{role}"')
            conn.exec_driver_sql(f'DROP ROLE "{role}"')
        admin.dispose()


def _run(url: str, *statements: str) -> None:
    """Run *statements* on *url* in one transaction, as the role *url* logs in as."""
    engine = create_engine(url, poolclass=NullPool)
    try:
        with engine.begin() as conn:
            for statement in statements:
                conn.exec_driver_sql(statement)
    finally:
        engine.dispose()


def _answer(url: str, query: str, **params: object) -> object:
    """The one value *query* answers on *url*, with *params* bound."""
    engine = create_engine(url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            return conn.execute(text(query), params).scalar()
    finally:
        engine.dispose()


def _may_execute(url: str, role: str, routine: str) -> bool:
    """Whether *role* (``public`` for PUBLIC) may execute *routine*, by its signature."""
    query = "SELECT has_function_privilege(:role, :routine, 'EXECUTE')"
    return bool(_answer(url, query, role=role, routine=routine))


@contextlib.contextmanager
def _sent() -> Iterator[list[str]]:
    """Every statement any engine sends while the block runs."""
    seen: list[str] = []

    def record(conn: object, cursor: object, statement: str, *rest: object) -> None:
        seen.append(statement)

    event.listen(Engine, "before_cursor_execute", record)
    try:
        yield seen
    finally:
        event.remove(Engine, "before_cursor_execute", record)


#: Every privilege the app's objects carry: routines, relations, schemas, the database and the
#: default privileges, one line each, in one string a second run must leave as it found it.
_PRIVILEGES = """
SELECT string_agg(entry, E'\\n' ORDER BY entry) FROM (
    SELECT 'routine ' || p.oid::regprocedure::text || ' ' || coalesce(p.proacl::text, '-')
        AS entry
    FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname !~ '^(pg_|information_schema$)'
    UNION ALL
    SELECT 'relation ' || c.oid::regclass::text || ' ' || coalesce(c.relacl::text, '-')
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname !~ '^(pg_|information_schema$)'
    UNION ALL
    SELECT 'schema ' || nspname || ' ' || coalesce(nspacl::text, '-') FROM pg_namespace
    UNION ALL
    SELECT 'database ' || coalesce(datacl::text, '-') FROM pg_database
    WHERE datname = current_database()
    UNION ALL
    SELECT 'default ' || defaclrole::regrole::text || ' ' || defaclnamespace::text || ' '
        || defaclobjtype::text || ' ' || defaclacl::text FROM pg_default_acl
) AS entries
"""


def test_grant_runtime_revokes_execute_on_what_migrations_made_and_triggers_still_fire(
    pg_url: str,
) -> None:
    """A ``SECURITY DEFINER`` function runs as its owner, and PUBLIC may execute every
    function by default: one a migration made would let the runtime role reach further than
    its grants. A trigger keeps firing once its function is revoked, because PostgreSQL checks
    ``EXECUTE`` on a trigger's function when the trigger is created, not each time it fires.
    """
    upgrade(pg_url, APP_ROOT, package="app", schema_layout="per-module")
    _run(  # what a migration, run as the owner, makes
        pg_url,
        "CREATE FUNCTION notes.probe_definer() RETURNS int LANGUAGE sql SECURITY DEFINER"
        " AS 'SELECT 1'",
        "CREATE PROCEDURE notes.probe_procedure() LANGUAGE sql AS 'SELECT 1'",
        "CREATE TABLE notes.probe (id int)",
        "CREATE TABLE notes.probe_log (id int)",
        "CREATE FUNCTION notes.probe_logged() RETURNS trigger LANGUAGE plpgsql"
        " AS $$BEGIN INSERT INTO notes.probe_log VALUES (NEW.id); RETURN NEW; END$$",
        "CREATE TRIGGER probe_logs AFTER INSERT ON notes.probe"
        " FOR EACH ROW EXECUTE FUNCTION notes.probe_logged()",
    )
    with _login(pg_url, "terp_rt") as (role, runtime_url):
        grant_runtime_role(
            pg_url,
            role,
            APP_ROOT,
            package="app",
            schema_layout="per-module",
            owner_role=make_url(pg_url).username,
        )
        runtime = create_engine(runtime_url, poolclass=NullPool)
        try:
            for refused, kind in (
                ("SELECT notes.probe_definer()", "function"),
                ("CALL notes.probe_procedure()", "procedure"),
            ):
                with runtime.connect() as conn, pytest.raises(
                    DBAPIError, match=f"permission denied for {kind} probe_"
                ):
                    conn.exec_driver_sql(refused)
            # The audit capability's own migration made a trigger function: swept the same way.
            assert not _may_execute(pg_url, "public", "audit.terp_audit_event_append_only()")
            # The grants hold, and the trigger fires for a role that may not execute it.
            with runtime.begin() as conn:
                conn.exec_driver_sql("INSERT INTO notes.probe VALUES (7)")
            with runtime.connect() as conn:
                assert conn.exec_driver_sql("SELECT id FROM notes.probe_log").scalar() == 7
            assert not _may_execute(pg_url, role, "notes.probe_logged()")
        finally:
            runtime.dispose()


def test_grant_runtime_revokes_aggregates_and_window_functions_by_name_too(pg_url: str) -> None:
    """PostgreSQL checks ``EXECUTE`` on an aggregate's state function against the
    aggregate's owner, not its caller: revoking a ``SECURITY DEFINER`` state function alone
    leaves it reachable through an aggregate made before grant-runtime ran. So aggregates
    are revoked by name like every routine, and window functions with them."""
    upgrade(pg_url, APP_ROOT, package="app", schema_layout="per-module")
    _run(  # what migrations, run as the owner, make; the window function is row_number's C
        pg_url,
        "CREATE SCHEMA probe_private",
        "CREATE TABLE probe_private.secret (v int)",
        "INSERT INTO probe_private.secret VALUES (99)",
        "CREATE FUNCTION notes.probe_peek(state int, x int) RETURNS int LANGUAGE sql"
        " SECURITY DEFINER AS 'SELECT max(v) FROM probe_private.secret'",
        "CREATE AGGREGATE notes.probe_peek_agg(int) (SFUNC = notes.probe_peek, STYPE = int)",
        "CREATE FUNCTION notes.probe_window() RETURNS bigint LANGUAGE internal WINDOW"
        " IMMUTABLE AS 'window_row_number'",
    )
    with _login(pg_url, "terp_rt") as (role, runtime_url):
        grant_runtime_role(
            pg_url,
            role,
            APP_ROOT,
            package="app",
            schema_layout="per-module",
            owner_role=make_url(pg_url).username,
        )
        runtime = create_engine(runtime_url, poolclass=NullPool)
        try:
            # The secret is beyond the runtime role's grants, and so is the state function:
            # the aggregate over it was the way round both.
            with runtime.connect() as conn, pytest.raises(
                DBAPIError, match="permission denied for schema probe_private"
            ):
                conn.exec_driver_sql("SELECT v FROM probe_private.secret")
            assert not _may_execute(pg_url, role, "notes.probe_peek(integer, integer)")
            for refused, denied in (
                ("SELECT notes.probe_peek_agg(1)", "aggregate probe_peek_agg"),
                ("SELECT notes.probe_window() OVER ()", "function probe_window"),
            ):
                with runtime.connect() as conn, pytest.raises(
                    DBAPIError, match=f"permission denied for {denied}"
                ):
                    conn.exec_driver_sql(refused)
        finally:
            runtime.dispose()


def test_a_routine_the_owner_makes_after_grant_runtime_is_not_public_either(pg_url: str) -> None:
    """The owner's global default, written without ``IN SCHEMA``: a default given per schema
    adds to the global one, which lets PUBLIC execute every new function, and cannot take it
    back. So it holds in a schema grant-runtime never named as well."""
    upgrade(pg_url, APP_ROOT, package="app", schema_layout="per-module")
    with _login(pg_url, "terp_rt") as (role, runtime_url):
        grant_runtime_role(
            pg_url,
            role,
            APP_ROOT,
            package="app",
            schema_layout="per-module",
            owner_role=make_url(pg_url).username,
        )
        _run(
            pg_url,
            "CREATE FUNCTION notes.probe_later() RETURNS int LANGUAGE sql SECURITY DEFINER"
            " AS 'SELECT 1'",
            "CREATE PROCEDURE audit.probe_later() LANGUAGE sql AS 'SELECT 1'",
            "CREATE SCHEMA probe_elsewhere",
            "CREATE FUNCTION probe_elsewhere.probe_later() RETURNS int LANGUAGE sql AS 'SELECT 1'",
        )
        runtime = create_engine(runtime_url, poolclass=NullPool)
        try:
            for refused, kind in (
                ("SELECT notes.probe_later()", "function"),
                ("CALL audit.probe_later()", "procedure"),
            ):
                with runtime.connect() as conn, pytest.raises(
                    DBAPIError, match=f"permission denied for {kind} probe_later"
                ):
                    conn.exec_driver_sql(refused)
        finally:
            runtime.dispose()
        assert not _may_execute(pg_url, "public", "probe_elsewhere.probe_later()")


def test_grant_runtime_runs_again_without_changing_anything(pg_url: str) -> None:
    """Idempotent: a second run leaves every privilege as the first left it and finds nothing
    to revoke by name, and a function granted to the runtime role by name keeps its grant,
    because grant-runtime revokes only what PUBLIC holds."""
    upgrade(pg_url, APP_ROOT, package="app", schema_layout="per-module")
    _run(pg_url, "CREATE FUNCTION notes.probe_called() RETURNS int LANGUAGE sql AS 'SELECT 1'")
    owner = make_url(pg_url).username
    with _login(pg_url, "terp_rt") as (role, runtime_url):
        with _sent() as first:
            grant_runtime_role(
                pg_url, role, APP_ROOT, package="app", schema_layout="per-module", owner_role=owner
            )
        assert "REVOKE EXECUTE ON FUNCTION notes.probe_called() FROM PUBLIC" in first
        _run(pg_url, f'GRANT EXECUTE ON FUNCTION notes.probe_called() TO "{role}"')
        before = _answer(pg_url, _PRIVILEGES)
        with _sent() as second:
            grant_runtime_role(
                pg_url, role, APP_ROOT, package="app", schema_layout="per-module", owner_role=owner
            )
        assert _answer(pg_url, _PRIVILEGES) == before
        assert [statement for statement in second if statement.startswith("REVOKE")] == []
        assert not _may_execute(pg_url, "public", "notes.probe_called()")
        assert _answer(runtime_url, "SELECT notes.probe_called()") == 1


def test_grant_runtime_refuses_a_routine_it_cannot_revoke_and_changes_nothing(
    pg_url: str,
) -> None:
    """PostgreSQL revokes only for a routine's owner, a member of its owning role or a
    superuser; from any other role, ``REVOKE`` is a WARNING that revokes nothing. So
    grant-runtime reads the catalog again and refuses what PUBLIC may still execute, and its
    one transaction takes back everything with it: the revocations it could make, the
    default, the grants."""
    admin = make_url(pg_url).username
    with _login(pg_url, "terp_own") as (owner, owner_url), _login(pg_url, "terp_rt") as (role, _):
        _run(
            pg_url,
            f'GRANT CREATE ON SCHEMA public TO "{owner}"',
            "CREATE FUNCTION public.probe_foreign() RETURNS int LANGUAGE sql SECURITY DEFINER"
            " AS 'SELECT 1'",
        )
        _run(
            owner_url,
            "CREATE TABLE public.probe (id int)",
            "CREATE FUNCTION public.probe_own() RETURNS int LANGUAGE sql AS 'SELECT 1'",
        )
        with pytest.raises(MigrationError) as refused:
            grant_runtime_role(owner_url, role, schema_layout="flat", owner_role=owner)
        assert f"PUBLIC may still execute public.probe_foreign() (owner {admin})" in str(
            refused.value
        )
        # Nothing changed: the routine it could revoke, the default and the grants.
        assert _may_execute(pg_url, "public", "public.probe_own()")
        defaults = "SELECT count(*) FROM pg_default_acl WHERE defaclrole = CAST(:owner AS regrole)"
        assert _answer(pg_url, defaults, owner=owner) == 0
        granted = "SELECT has_table_privilege(:role, 'public.probe', 'SELECT')"
        assert not _answer(pg_url, granted, role=role)


def test_grant_runtime_leaves_an_extension_s_functions_to_the_extension(pg_url: str) -> None:
    """An extension's script decides what PUBLIC may call, and its operators are its
    interface: revoked, citext's own ``=`` would refuse the runtime role a plain comparison.
    Nor could the owner revoke them: a superuser created the extension, so they are its."""
    with _login(pg_url, "terp_own") as (owner, owner_url), _login(pg_url, "terp_rt") as (
        role,
        runtime_url,
    ):
        _run(
            pg_url,
            f'GRANT CREATE ON SCHEMA public TO "{owner}"',
            "CREATE EXTENSION citext SCHEMA public",
        )
        _run(
            owner_url,
            "CREATE TABLE public.probe (email public.citext)",
            "INSERT INTO public.probe VALUES ('Someone@example.com')",
        )
        grant_runtime_role(owner_url, role, schema_layout="flat", owner_role=owner)
        assert _may_execute(pg_url, "public", "public.citext_eq(public.citext, public.citext)")
        assert _answer(
            runtime_url, "SELECT count(*) FROM public.probe WHERE email = 'someone@example.com'"
        ) == 1


def test_cli_grant_runtime_reports_the_surfaces(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: dict[str, object] = {}

    def _fake_grant(*args: object, **kwargs: object) -> list[str]:
        seen.update(kwargs)
        return ["notes", "public"]

    monkeypatch.setattr(migrate_cli, "grant_runtime_role", _fake_grant)
    migrate_main(
        [
            "grant-runtime",
            "terp_rt",
            "--owner-role",
            "terp_owner",
            "--database-url",
            "postgresql://u:p@h/db",
        ]
    )
    out = capsys.readouterr().out
    assert "terp_rt" in out and "notes" in out
    assert "revoked EXECUTE from PUBLIC" in out
    assert seen["owner_role"] == "terp_owner"


def test_cli_grant_runtime_fails_closed(capsys: pytest.CaptureFixture[str]) -> None:
    # A bad role name never opens a connection; the CLI exits non-zero with the reason.
    with pytest.raises(SystemExit) as excinfo:
        migrate_main(
            ["grant-runtime", "bad role", "--database-url", "postgresql://u:p@h/db"]
        )
    assert excinfo.value.code == 1
    assert "plain identifier" in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# check-roles (ADR 0071, amended 2026-11-14): an external database's two roles, read
# from the catalog as the owner before anything is backed up or migrated.
# --------------------------------------------------------------------------- #
@contextlib.contextmanager
def _owned_database(pg_url: str) -> Iterator[tuple[str, str, str]]:
    """A fresh owner role that owns *pg_url*'s database, its URL, and a fresh runtime role.

    The shape of an external database before its first deploy: the owner owns the database
    (and so ``public``, through ``pg_database_owner``), and the runtime role is a plain login.
    """
    database, admin = make_url(pg_url).database, make_url(pg_url).username
    with _login(pg_url, "terp_own") as (owner, owner_url), _login(pg_url, "terp_rt") as (role, _):
        _run(pg_url, f'ALTER DATABASE "{database}" OWNER TO "{owner}"')
        try:
            yield owner, owner_url, role
        finally:
            _run(pg_url, f'ALTER DATABASE "{database}" OWNER TO "{admin}"')


#: Every role, membership and owner the server holds, one line each, beside _PRIVILEGES.
_ROLES_AND_OWNERS = """
SELECT string_agg(entry, E'\\n' ORDER BY entry) FROM (
    SELECT 'role ' || rolname || ' ' || concat_ws(',', rolsuper, rolinherit, rolcreaterole,
        rolcreatedb, rolcanlogin, rolreplication, rolbypassrls) AS entry FROM pg_roles
    UNION ALL
    SELECT 'member ' || roleid::regrole::text || ' ' || member::regrole::text || ' '
        || admin_option::text FROM pg_auth_members
    UNION ALL
    SELECT 'schema ' || nspname || ' ' || nspowner::regrole::text FROM pg_namespace
    UNION ALL
    SELECT 'relation ' || c.oid::regclass::text || ' ' || c.relowner::regrole::text
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname !~ '^(pg_|information_schema$)'
    UNION ALL
    SELECT 'database ' || datname || ' ' || datdba::regrole::text FROM pg_database
) AS entries
"""


@pytest.mark.parametrize("layout", ["flat", "per-module"])
def test_check_roles_passes_a_pair_shaped_by_grant_runtime(pg_url: str, layout: str) -> None:
    labels = [tree.label for tree in resolve_all_migration_trees(APP_ROOT, package="app")]
    expected = ["public"] if layout == "flat" else [*labels, "public"]
    with _owned_database(pg_url) as (owner, owner_url, role):
        upgrade(owner_url, APP_ROOT, package="app", schema_layout=layout)
        grant_runtime_role(
            owner_url, role, APP_ROOT, package="app", schema_layout=layout, owner_role=owner
        )
        found = check_roles(
            owner_url, role, APP_ROOT, owner_role=owner, package="app", schema_layout=layout
        )
    assert found == RoleCheck(schemas=tuple(expected), pending=(), failures=())


#: Each fault alone, as the server's admin makes it: the layout it is checked under, the
#: statements, what the one failure says, and what it says to change.
_ALONE = {
    "superuser": (
        "flat", ['ALTER ROLE "{role}" SUPERUSER'], "is a superuser", 'NOSUPERUSER'
    ),
    "createrole": (
        "flat", ['ALTER ROLE "{role}" CREATEROLE'], "has CREATEROLE", "NOCREATEROLE"
    ),
    "createdb": ("flat", ['ALTER ROLE "{role}" CREATEDB'], "has CREATEDB", "NOCREATEDB"),
    "replication": (
        "flat", ['ALTER ROLE "{role}" REPLICATION'], "has REPLICATION", "NOREPLICATION"
    ),
    "bypassrls": (
        "flat", ['ALTER ROLE "{role}" BYPASSRLS'], "has BYPASSRLS", "NOBYPASSRLS"
    ),
    "create-in-the-database": (
        "flat",
        ['GRANT CREATE ON DATABASE "{database}" TO "{role}"'],
        "may CREATE in database",
        'REVOKE CREATE ON DATABASE "{database}" FROM "{role}"',
    ),
    "create-in-public-as-before-postgresql-15": (
        "flat",
        ["GRANT CREATE ON SCHEMA public TO PUBLIC"],
        "may CREATE in schema 'public'",
        'REVOKE CREATE ON SCHEMA "public" FROM "{role}", and from PUBLIC',
    ),
    "create-in-an-app-schema": (
        "per-module",
        ['CREATE SCHEMA notes AUTHORIZATION "{owner}"', 'GRANT CREATE ON SCHEMA notes TO "{role}"'],
        "may CREATE in schema 'notes'",
        'REVOKE CREATE ON SCHEMA "notes" FROM "{role}"',
    ),
    "owns-a-relation": (
        "flat",
        ["CREATE TABLE public.probe (id int)", 'ALTER TABLE public.probe OWNER TO "{role}"'],
        "can act as the owner of 1 relation(s) in the app's schemas: 'public.probe' (table",
        'OWNER TO "{owner}"',
    ),
    "owns-a-relation-through-another-role": (
        "flat",
        [
            "CREATE TABLE public.probe (id int)",
            'ALTER TABLE public.probe OWNER TO "{other}"',
            'GRANT "{other}" TO "{role}"',
        ],
        "'public.probe' (table, owned by '{other}')",
        "REASSIGN OWNED BY their owner TO \"{owner}\"",
    ),
    "member-of-the-owner": (  # the owner's own table is that membership's, not a second line
        "flat",
        [
            "CREATE TABLE public.probe (id int)",
            'ALTER TABLE public.probe OWNER TO "{owner}"',
            'GRANT "{owner}" TO "{role}"',
        ],
        "is a member of the owner role",
        'REVOKE "{owner}" FROM "{role}"',
    ),
    "member-through-a-noinherit-role": (
        "flat",
        ['ALTER ROLE "{role}" NOINHERIT', 'GRANT "{owner}" TO "{other}"', 'GRANT "{other}" TO "{role}"'],
        "is a member of the owner role",
        'REVOKE "{owner}" FROM "{role}", or from the role it holds it through',
    ),
    "an-app-schema-another-role-owns": (
        "per-module",
        ['CREATE SCHEMA notes AUTHORIZATION "{other}"'],
        "schema 'notes' is owned by '{other}', not the owner role '{owner}'",
        'ALTER SCHEMA "notes" OWNER TO "{owner}"',
    ),
    "public-the-runtime-role-can-act-as-owner-of": (
        "flat",
        ['ALTER ROLE "{role}" NOINHERIT', 'ALTER SCHEMA public OWNER TO "{other}"', 'GRANT "{other}" TO "{role}"'],
        "can act as the owner of schema 'public'",
        'ALTER SCHEMA public OWNER TO "{owner}"',
    ),
}


@pytest.mark.parametrize("fault", sorted(_ALONE))
def test_check_roles_names_each_failure_alone_and_what_to_change(pg_url: str, fault: str) -> None:
    layout, statements, says, change = _ALONE[fault]
    with _owned_database(pg_url) as (owner, owner_url, role), _login(pg_url, "terp_other") as (
        other,
        _,
    ):
        names = {"role": role, "owner": owner, "other": other}
        names["database"] = make_url(pg_url).database

        def check() -> RoleCheck:
            return check_roles(owner_url, role, APP_ROOT, owner_role=owner, schema_layout=layout)

        assert check().failures == ()  # the pair holds before the fault
        _run(pg_url, *(statement.format(**names) for statement in statements))
        found = check()
    assert len(found.failures) == 1, found.failures
    assert says.format(**names) in found.failures[0]
    assert change.format(**names) in found.failures[0]


@pytest.mark.parametrize(
    ("runtime", "owning", "says"),
    [
        ("{role}_gone", "{owner}", "the runtime role '{role}_gone' does not exist"),
        ("{role}", "{owner}_gone", "the owner role '{owner}_gone' does not exist"),
        ("{owner}", "{owner}", "the runtime role and the owner role are both '{owner}'"),
    ],
)
def test_check_roles_names_a_missing_role_and_one_role_for_both(
    pg_url: str, runtime: str, owning: str, says: str
) -> None:
    with _owned_database(pg_url) as (owner, owner_url, role):
        names = {"role": role, "owner": owner}
        found = check_roles(
            owner_url,
            runtime.format(**names),
            APP_ROOT,
            owner_role=owning.format(**names),
            schema_layout="flat",
        )
    assert len(found.failures) == 1, found.failures
    assert found.failures[0].startswith(says.format(**names))


def test_check_roles_lists_every_failure_at_once(pg_url: str) -> None:
    with _owned_database(pg_url) as (owner, owner_url, role), _login(pg_url, "terp_other") as (
        other,
        _,
    ):
        database = make_url(pg_url).database
        _run(
            pg_url,
            f'ALTER ROLE "{role}" CREATEDB',
            f'GRANT CREATE ON DATABASE "{database}" TO "{role}"',
            "GRANT CREATE ON SCHEMA public TO PUBLIC",
            f'CREATE SCHEMA notes AUTHORIZATION "{other}"',
            *[f"CREATE TABLE public.probe_{n} (id int)" for n in range(4)],
            "CREATE VIEW public.probe_view AS SELECT 1 AS one",
            "CREATE SEQUENCE public.probe_sequence",
            *[f'ALTER TABLE public.probe_{n} OWNER TO "{role}"' for n in range(4)],
            f'ALTER VIEW public.probe_view OWNER TO "{role}"',
            f'ALTER SEQUENCE public.probe_sequence OWNER TO "{role}"',
        )
        found = check_roles(owner_url, role, APP_ROOT, owner_role=owner, schema_layout="per-module")
    said = [
        "has CREATEDB",
        "can act as the owner of 6 relation(s)",
        "may CREATE in database",
        "may CREATE in schema 'public'",
        f"schema 'notes' is owned by '{other}'",
    ]
    assert len(found.failures) == len(said), found.failures
    for failure, fragment in zip(found.failures, said, strict=True):
        assert fragment in failure
    assert "and 1 more" in found.failures[1]  # five are named, the rest counted
    assert found.schemas == ("notes", "public")
    assert "audit" in found.pending and "notes" not in found.pending


def test_check_roles_changes_nothing(pg_url: str) -> None:
    """It holds the transaction read-only, sends only reads, and leaves every privilege, role,
    membership and owner as it found them, though it finds faults to report."""
    with _owned_database(pg_url) as (owner, owner_url, role):
        _run(
            pg_url,
            f'ALTER ROLE "{role}" CREATEDB',
            "CREATE TABLE public.probe (id int)",
            f'ALTER TABLE public.probe OWNER TO "{role}"',
        )
        before = (_answer(pg_url, _PRIVILEGES), _answer(pg_url, _ROLES_AND_OWNERS))
        with _sent() as seen:
            found = check_roles(owner_url, role, APP_ROOT, owner_role=owner, schema_layout="flat")
        after = (_answer(pg_url, _PRIVILEGES), _answer(pg_url, _ROLES_AND_OWNERS))
    assert len(found.failures) == 2 and after == before
    statements = [statement.strip() for statement in seen]
    start = statements.index("SET TRANSACTION READ ONLY")
    assert any("pg_roles" in statement for statement in statements[start + 1 :])
    rest = statements[:start] + statements[start + 1 :]
    assert all(statement.lower().startswith(("select", "show")) for statement in rest), rest


def test_cli_check_roles_exits_0_or_1_and_never_prints_the_connection(
    pg_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with _owned_database(pg_url) as (owner, owner_url, role):
        argv = [
            "check-roles",
            role,
            "--owner-role",
            owner,
            "--database-url",
            owner_url,
            "--app-root",
            str(APP_ROOT),
            "--schema-layout",
            "per-module",
        ]
        migrate_main(argv)
        passed = capsys.readouterr()
        _run(pg_url, f'ALTER ROLE "{role}" CREATEDB', f'ALTER ROLE "{role}" BYPASSRLS')
        with pytest.raises(SystemExit) as refused:
            migrate_main(argv)
        failed = capsys.readouterr()
    assert passed.out.count("\n") == 1 and passed.err == ""
    assert f"'{role}'" in passed.out and f"'{owner}'" in passed.out
    assert "hold on ['public']; not created yet: [" in passed.out
    assert refused.value.code == 1 and failed.out == ""
    lines = failed.err.splitlines()
    assert len(lines) == 2 and "CREATEDB" in lines[0] and "BYPASSRLS" in lines[1]
    for output in (passed.out, failed.err):
        assert "rt-secret" not in output and owner_url not in output


def test_cli_check_roles_says_it_could_not_connect_without_the_connection(
    pg_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    # A login that does not exist fails whatever the server's authentication method.
    unknown = make_url(pg_url).set(username=f"terp_nobody_{uuid.uuid4().hex[:8]}", password="pw-9f3k2")
    url = unknown.render_as_string(hide_password=False)
    with pytest.raises(SystemExit) as refused:
        migrate_main(["check-roles", "terp_rt", "--owner-role", "terp_owner", "--database-url", url])
    err = capsys.readouterr().err
    assert refused.value.code == 1 and err.count("\n") == 1
    assert "could not connect to the database as the owner" in err
    for value in ("pw-9f3k2", unknown.username, unknown.host, str(unknown.port)):
        assert value not in err


@pytest.mark.parametrize(
    ("role", "owner"),
    [("bad role", "terp_owner"), ("terp_rt", 'owner"; DROP ROLE x'), ("terp_rt\n", "terp_owner")],
)
def test_cli_check_roles_refuses_a_name_that_is_not_plain_before_connecting(
    role: str, owner: str, capsys: pytest.CaptureFixture[str]
) -> None:
    # host.invalid never resolves: a refusal that reached for the server would say so instead.
    url = "postgresql+psycopg://u:secret@host.invalid/appdb"
    with pytest.raises(SystemExit) as refused:
        migrate_main(["check-roles", role, "--owner-role", owner, "--database-url", url])
    assert refused.value.code == 1
    assert "is not a plain identifier" in capsys.readouterr().err


def test_cli_check_roles_needs_an_owner_role_and_postgresql(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    url = f"sqlite:///{tmp_path / 'app.db'}"
    with pytest.raises(SystemExit) as unnamed:
        migrate_main(["check-roles", "terp_rt", "--database-url", url])
    assert unnamed.value.code == 2 and "--owner-role" in capsys.readouterr().err
    with pytest.raises(SystemExit) as refused:
        migrate_main(
            ["check-roles", "terp_rt", "--owner-role", "terp_owner", "--database-url", url]
        )
    assert refused.value.code == 1
    assert "check-roles requires PostgreSQL" in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# The restore drill                                                             #
# --------------------------------------------------------------------------- #
#
# Backup is the one operational control with no partial credit, and it is the last
# thing anyone writes. What this stack has instead is one sentence in DEPLOYMENT.md
# naming the volume the state lives in.
#
# The reason that is not enough here is specific to the per-package layout. A Terp app's
# schema is not one history: every table-owning package keeps its own, behind its own
# `alembic_version_<label>` table, and the boot guard refuses to start when ANY package's
# schema is behind. So a restore that loses or truncates one of those bookkeeping tables
# does not fail loudly at restore time -- it fails at the next boot, with a message about
# pending migrations, which reads as a deploy problem rather than as a bad backup. ADR
# 0090 records that observation as a docstring aside. This makes it a test.


def _libpq_url(url: str) -> str:
    """The SQLAlchemy URL as something ``pg_dump`` will accept."""
    return make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)


def _pg_client_version() -> tuple[int, ...] | None:
    """The local ``pg_dump``'s version, or ``None`` when it is not installed."""
    binary = shutil.which("pg_dump")
    if binary is None:
        return None
    result = subprocess.run(  # fixed argv, no shell
        [binary, "--version"], capture_output=True, text=True, check=False
    )
    match = re.search(r"(\d+)(?:\.(\d+))?", result.stdout)
    return tuple(int(part) for part in match.groups() if part) if match else None


def _server_major(url: str) -> int:
    engine = create_engine(url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            return int(conn.exec_driver_sql("SHOW server_version_num").scalar()) // 10000
    finally:
        engine.dispose()


@pytest.fixture
def pg_url_pair() -> Iterator[tuple[str, str]]:
    """Two independent scratch databases: one to migrate and dump, one to restore into.

    Restoring over the database the dump came from would prove nothing -- the tables are
    already there and already current, so every assertion passes whatever the dump
    contains. The clean target is the whole point.
    """
    # The SHIPPED scratch-database helper, for the same reason `db_url` above consumes
    # the shipped fixture: this file used to carry its own copy, and two copies of the
    # code that creates and force-drops a database drift in exactly the way that leaves
    # scratch databases behind on a shared server.
    from terp.core.testing import _postgres_scratch_database

    started: list[Iterator[str]] = []
    urls: list[str] = []
    try:
        for _ in range(2):
            generator = _postgres_scratch_database()
            # Appended BEFORE it is advanced, so a failure in the second CREATE DATABASE
            # still tears the first one down. Building the list first and advancing it
            # after leaked a `terp_conformance_<hex>` database on every such failure, on
            # a server this suite shares with itself.
            started.append(generator)
            urls.append(next(generator))
        yield (urls[0], urls[1])
    finally:
        for generator in started:
            # Each drop is independent: an error dropping the first must not skip the
            # second. StopIteration is the normal end of the fixture's own teardown.
            with contextlib.suppress(StopIteration, DBAPIError, OSError):
                next(generator)


def _absent_lane(reason: str) -> None:
    """Skip, or fail when the running lane declared that it must not have to.

    The lane sets ``TERP_REQUIRE_POSTGRES_LANE`` to turn this lane's skips into failures.
    A skip is GREEN, and a check that silently does not run is worse than not having one,
    because the green implies it ran. Locally the skip is right -- a developer with no
    PostgreSQL and no client tools should not be blocked by a PostgreSQL-only lane. In the
    lane, where the workflow starts a server and installs a matching client on purpose, a
    skip means one of those steps stopped working and nothing else would say so.
    """
    if os.environ.get(TERP_REQUIRE_POSTGRES_LANE_ENV):
        pytest.fail(
            f"{reason}. {TERP_REQUIRE_POSTGRES_LANE_ENV} is set, so this is a failure "
            "rather than a skip: the lane is configured to run these tests and cannot"
        )
    pytest.skip(reason)


def _require_pg_client(url: str) -> None:
    client = _pg_client_version()
    if client is None:
        _absent_lane("pg_dump is not installed — the restore drill needs the client tools")
        return
    server = _server_major(url)
    if client[0] < server:
        _absent_lane(
            f"pg_dump is {client[0]} and the server is {server}; pg_dump refuses a "
            "newer server, so install the matching postgresql-client"
        )


@pytest.mark.parametrize(("client", "server"), [(None, 17), ((16, 4), 17)], ids=["missing", "older"])
def test_the_restore_drill_skips_without_a_usable_pg_dump_and_fails_in_the_lane(
    monkeypatch: pytest.MonkeyPatch, client: tuple[int, ...] | None, server: int
) -> None:
    # Neither branch runs in the lane itself, which installs a matching client, so only
    # this test notices when the decision they reach stops being a skip or a failure.
    monkeypatch.setitem(globals(), "_pg_client_version", lambda: client)
    monkeypatch.setitem(globals(), "_server_major", lambda url: server)
    monkeypatch.delenv(TERP_REQUIRE_POSTGRES_LANE_ENV, raising=False)
    with pytest.raises(pytest.skip.Exception, match="pg_dump"):
        _require_pg_client("postgresql://unused")
    monkeypatch.setenv(TERP_REQUIRE_POSTGRES_LANE_ENV, "1")
    with pytest.raises(pytest.fail.Exception, match="failure rather than a skip"):
        _require_pg_client("postgresql://unused")


def test_the_restore_drill_proceeds_with_a_matching_pg_dump(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(globals(), "_pg_client_version", lambda: (17, 2))
    monkeypatch.setitem(globals(), "_server_major", lambda url: 17)
    monkeypatch.setenv(TERP_REQUIRE_POSTGRES_LANE_ENV, "1")
    assert _require_pg_client("postgresql://unused") is None


def _dump(url: str, target: pathlib.Path, *, exclude: str | None = None) -> None:
    argv = ["pg_dump", "--format=custom", f"--file={target}"]
    if exclude is not None:
        argv.append(f"--exclude-table={exclude}")
    argv.append(_libpq_url(url))
    subprocess.run(argv, check=True, capture_output=True)


def _restore(dump: pathlib.Path, url: str) -> None:
    subprocess.run(
        [
            "pg_restore",
            "--no-owner",
            "--no-privileges",
            f"--dbname={_libpq_url(url)}",
            str(dump),
        ],
        check=True,
        capture_output=True,
    )


def test_a_restored_database_boots(
    pg_url_pair: tuple[str, str], tmp_path: pathlib.Path
) -> None:
    """Dump a fully migrated database, restore it into a clean one, and boot.

    The assertion that matters is the boot guard, not the table count: it is what a
    deploy actually runs, and it is what a lost `alembic_version_<label>` breaks.
    """
    source, target = pg_url_pair
    _require_pg_client(source)
    upgrade(source, APP_ROOT, package="app")

    dump = tmp_path / "terp.dump"
    _dump(source, dump)
    _restore(dump, target)

    assert _table_names(target) == _table_names(source), (
        "the restored database does not hold the same tables as the one dumped"
    )
    engine = create_engine(target)
    try:
        assert_migrations_current(engine, APP_ROOT, package="app")  # no raise
    finally:
        engine.dispose()


def test_every_package_history_survives_the_round_trip(
    pg_url_pair: tuple[str, str], tmp_path: pathlib.Path
) -> None:
    """Thirteen histories, thirteen bookkeeping tables, and each one has to arrive with
    its revision intact — a restored `alembic_version_notes` holding no row is a
    database that boots into "notes is behind" and re-runs a migration over live data."""
    source, target = pg_url_pair
    _require_pg_client(source)
    upgrade(source, APP_ROOT, package="app")

    dump = tmp_path / "terp.dump"
    _dump(source, dump)
    _restore(dump, target)

    for label in _EXPECTED_LABELS:
        before = _version_row(source, label)
        after = _version_row(target, label)
        assert before is not None, f"alembic_version_{label} was never written"
        assert after == before, (
            f"alembic_version_{label} did not survive the round trip "
            f"({before!r} -> {after!r})"
        )


def test_a_restore_that_loses_one_history_is_refused_at_boot(
    pg_url_pair: tuple[str, str], tmp_path: pathlib.Path
) -> None:
    """The drill's own proof that it is measuring something.

    A dump that omits one bookkeeping table restores WITHOUT ERROR: every real table is
    there, the data is there, nothing complains. The damage only appears when the app
    starts — which is exactly why this belongs in a test rather than in a runbook.
    """
    source, target = pg_url_pair
    _require_pg_client(source)
    upgrade(source, APP_ROOT, package="app")

    dump = tmp_path / "partial.dump"
    _dump(source, dump, exclude="alembic_version_notes")
    _restore(dump, target)

    assert "note" in _table_names(target), "the data tables restored fine — that is the trap"
    engine = create_engine(target)
    try:
        with pytest.raises(PendingMigrationsError):
            assert_migrations_current(engine, APP_ROOT, package="app")
    finally:
        engine.dispose()


def _version_row(url: str, label: str) -> str | None:
    engine = create_engine(url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            return conn.exec_driver_sql(
                f"SELECT version_num FROM alembic_version_{label}"  # noqa: S608
            ).scalar()
    except DBAPIError:
        return None
    finally:
        engine.dispose()
