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

import os
import pathlib
import uuid
from collections.abc import Iterator

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.pool import NullPool

from terp.core import ModuleSpec, Policy, create_app
from terp.core.migrations import resolve_migration_trees
from terp.migrations import (
    MigrationDriftError,
    MigrationError,
    PendingMigrationsError,
    adopt_schemas,
    assert_migrations_current,
    assert_migrations_match_models,
    downgrade,
    grant_runtime_role,
    heads,
    migration_status,
    stamp,
    upgrade,
    upgrade_sql,
)
from terp.migrations import cli as migrate_cli
from terp.migrations._config import alembic_config_for
from terp.migrations.cli import migrate_main

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
APP_ROOT = _REPO_ROOT / "apps" / "example" / "app"

_EXPECTED_LABELS = ["access", "audit", "files", "groups", "identity", "outbox", "sync", "webhooks", "journals", "notes", "projects", "tasks"]
_DOMAIN_TABLES = {
    "access_grant",
    "audit_event",
    "file_object",
    "identity_user",
    "identity_federated_identity",
    "journal",
    "note",
    "outbox_message",
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


_POSTGRES_URL_ENV = "TERP_TEST_POSTGRES_URL"


def _postgres_scratch_database() -> Iterator[str]:
    """A scratch PostgreSQL database for one test (skips without a configured server)."""
    admin_url = os.environ.get(_POSTGRES_URL_ENV)
    if not admin_url:
        pytest.skip(f"set {_POSTGRES_URL_ENV} to run the PostgreSQL conformance lane")
    scratch = f"terp_conformance_{uuid.uuid4().hex[:12]}"
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    try:
        with admin.connect() as conn:
            conn.exec_driver_sql(f'CREATE DATABASE "{scratch}"')
        yield make_url(admin_url).set(database=scratch).render_as_string(hide_password=False)
    finally:
        with admin.connect() as conn:
            conn.exec_driver_sql(f'DROP DATABASE IF EXISTS "{scratch}" WITH (FORCE)')
        admin.dispose()


@pytest.fixture(params=["sqlite", "postgresql"])
def db_url(request: pytest.FixtureRequest, tmp_path: pathlib.Path) -> Iterator[str]:
    """Every conformance test runs on SQLite and on the verified production dialect.

    The PostgreSQL lane (ADR 0069) runs when ``TERP_TEST_POSTGRES_URL`` points at a
    server (CI provides one; locally the lane skips). SQLite alone would keep masking
    real differences — VARCHAR length enforcement, timezone-aware datetimes, native
    ALTER vs batch mode — so the migration subsystem must hold on both. Each test
    gets its own scratch database so runs are isolated and repeatable.
    """
    if request.param == "sqlite":
        yield f"sqlite:///{tmp_path / 'conformance.db'}"
        return
    yield from _postgres_scratch_database()


@pytest.fixture
def pg_url() -> Iterator[str]:
    """A PostgreSQL-only scratch database (the per-module layout is PG-only)."""
    yield from _postgres_scratch_database()


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
    migrate_main(["make", "widgets", "-m", "create widgets", "--database-url", "sqlite://"])
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
    migrate_main(["make", "widgets", "--database-url", "sqlite://"])
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
            ["check", "--database-url", "sqlite://", "--app-root", str(missing)]
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

    with pytest.raises(Exception):  # noqa: B017 - the driver's error class is incidental
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
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        migrate_main(["adopt-schemas", "--database-url", "sqlite://"])
    assert excinfo.value.code == 1
    assert "PostgreSQL" in capsys.readouterr().err


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
                # …and refuses tampering with migration state (public is read-only).
                "DELETE FROM public.alembic_version_notes WHERE 1=0",
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
    assert seen["owner_role"] == "terp_owner"


def test_cli_grant_runtime_fails_closed(capsys: pytest.CaptureFixture[str]) -> None:
    # A bad role name never opens a connection; the CLI exits non-zero with the reason.
    with pytest.raises(SystemExit) as excinfo:
        migrate_main(
            ["grant-runtime", "bad role", "--database-url", "postgresql://u:p@h/db"]
        )
    assert excinfo.value.code == 1
    assert "plain identifier" in capsys.readouterr().err
