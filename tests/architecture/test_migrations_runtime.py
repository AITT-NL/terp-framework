"""Unit tests for the Alembic env delegate, config builder, and ``make``.

Covers the table-ownership scoping (so one package's autogenerate never proposes
another package's tables), the per-package Alembic ``Config``, and authoring a new
revision — without writing into any real package tree.
"""

from __future__ import annotations

import pathlib
from types import SimpleNamespace

import pytest

from terp.core.migrations import MigrationTree
from terp.migrations import _runtime, make, orchestrate
from terp.migrations._config import alembic_config_for
from terp.migrations._runtime import (
    _dependency_edges,
    _homeless_tables,
    _import_model_module,
    _model_modules,
    _references_any,
    _render_as_batch,
    _toposort,
    owned_table_names,
    scoped_filters,
    unmapped_tables,
    unowned_tables,
)
from terp.migrations.errors import MigrationError

# Import a real capability model so its table is registered for the ownership tests.
import terp.capabilities.audit.models  # noqa: E402,F401
import terp.capabilities.identity.models  # noqa: E402,F401


def test_owned_table_names_scopes_to_the_package() -> None:
    owned = owned_table_names("terp.capabilities.audit")
    assert "audit_event" in owned
    assert "identity_user" not in owned


def test_scoped_filters_limit_tables_to_owned() -> None:
    include_name, include_object = scoped_filters(frozenset({"audit_event"}))
    assert include_name("audit_event", "table", None) is True
    assert include_name("identity_user", "table", None) is False
    assert include_name("ix_audit_event_action", "index", None) is True
    assert include_object(object(), "audit_event", "table", False, None) is True
    assert include_object(object(), "identity_user", "table", False, None) is False
    assert include_object(object(), "a_column", "column", False, None) is True


def test_alembic_config_carries_the_package_scope() -> None:
    tree = MigrationTree(
        label="audit",
        import_path="terp.capabilities.audit",
        path=pathlib.Path("/x/migrations"),
    )
    config = alembic_config_for(tree, "sqlite:///y.db")
    assert config.get_main_option("terp_import_path") == "terp.capabilities.audit"
    assert config.get_main_option("terp_version_table") == "alembic_version_audit"
    assert config.get_main_option("sqlalchemy.url") == "sqlite:///y.db"
    # A lone path never contains a newline, so spaces / drive colons stay one location.
    assert config.get_main_option("path_separator") == "newline"


def test_make_autogenerates_only_owned_tables(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Target the real audit models but write the revision into a throwaway tree, so
    # autogenerate (which imports the models, diffs the empty DB, and applies the
    # ownership filters) is exercised without touching the real package.
    tree = MigrationTree(
        label="audit",
        import_path="terp.capabilities.audit",
        path=tmp_path / "migrations",
    )
    monkeypatch.setattr(orchestrate, "resolve_migration_target", lambda *a, **k: tree)

    make("audit", "create audit", f"sqlite:///{tmp_path / 'make.db'}", autogenerate=True)

    revisions = list((tmp_path / "migrations" / "versions").glob("*.py"))
    assert len(revisions) == 1
    body = revisions[0].read_text(encoding="utf-8")
    assert "create_table('audit_event'" in body
    # identity_user is registered in the shared metadata but not owned by audit.
    assert "identity_user" not in body


def test_render_as_batch_is_gated_to_sqlite() -> None:
    # Batch ALTER is a SQLite workaround; native dialects must ALTER directly.
    sqlite_conn = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))
    pg_conn = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    assert _render_as_batch(sqlite_conn) is True
    assert _render_as_batch(pg_conn) is False


def test_model_modules_includes_every_discovered_package() -> None:
    # Autogenerating one package must import the others' models so cross-package
    # foreign keys (e.g. a module -> identity_user) resolve against the metadata.
    _REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
    app_root = _REPO_ROOT / "apps" / "example" / "app"
    mods = _model_modules("app.modules.notes", str(app_root), "app")
    assert "app.modules.notes.models" in mods  # the target itself
    assert "terp.capabilities.identity.models" in mods  # a capability FK target
    assert "app.modules.tasks.models" in mods  # a sibling app module


def test_unowned_tables_flags_a_homeless_table() -> None:
    import sqlalchemy as sa
    from sqlalchemy import Column, Table
    from sqlmodel import SQLModel

    # A bare association Table has no mapper, so no package owns it.
    link = Table(
        "rt_unowned_link",
        SQLModel.metadata,
        Column("a_id", sa.Uuid, primary_key=True),
        Column("b_id", sa.Uuid, primary_key=True),
    )
    try:
        homeless = unowned_tables(["terp.capabilities.audit"])
        assert "rt_unowned_link" in homeless
        assert "audit_event" not in homeless
    finally:
        SQLModel.metadata.remove(link)  # keep the shared metadata clean for other tests


def _write_revision(versions: pathlib.Path, rid: str, down: str | None) -> None:
    versions.joinpath(f"{rid}.py").write_text(
        f'"""rev {rid}"""\n'
        "from __future__ import annotations\n"
        f"revision = {rid!r}\n"
        f"down_revision = {down!r}\n"
        "branch_labels = None\n"
        "depends_on = None\n"
        "def upgrade() -> None:\n    pass\n"
        "def downgrade() -> None:\n    pass\n",
        encoding="utf-8",
    )


def test_heads_reports_divergence_and_merge_resolves_it(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    versions = tmp_path / "migrations" / "versions"
    versions.mkdir(parents=True)
    _write_revision(versions, "base0001", None)
    _write_revision(versions, "brancha002", "base0001")  # developer A
    _write_revision(versions, "branchb003", "base0001")  # developer B -> two heads
    tree = MigrationTree("audit", "terp.capabilities.audit", tmp_path / "migrations")
    monkeypatch.setattr(orchestrate, "resolve_migration_trees", lambda *a, **k: [tree])
    monkeypatch.setattr(orchestrate, "resolve_migration_target", lambda *a, **k: tree)
    db = f"sqlite:///{tmp_path / 'h.db'}"

    assert sorted(orchestrate.heads(db)["audit"]) == ["brancha002", "branchb003"]

    orchestrate.merge_heads("audit", "merge dev branches", db)
    assert len(orchestrate.heads(db)["audit"]) == 1


def test_merge_heads_requires_at_least_two_heads(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    versions = tmp_path / "migrations" / "versions"
    versions.mkdir(parents=True)
    _write_revision(versions, "only0001", None)
    tree = MigrationTree("audit", "terp.capabilities.audit", tmp_path / "migrations")
    monkeypatch.setattr(orchestrate, "resolve_migration_target", lambda *a, **k: tree)
    with pytest.raises(MigrationError, match="at least two"):
        orchestrate.merge_heads("audit", "x", f"sqlite:///{tmp_path / 'x.db'}")


def test_downgrade_rejects_a_package_specific_revision_without_a_label() -> None:
    # A concrete hash is meaningless to every other package's history.
    with pytest.raises(MigrationError, match="package-specific"):
        orchestrate.downgrade("sqlite://", revision="deadbeef1234")


def test_unmapped_tables_flags_a_bare_table() -> None:
    import sqlalchemy as sa
    from sqlalchemy import Column, Table
    from sqlmodel import SQLModel

    link = Table("rt_bare_link", SQLModel.metadata, Column("a_id", sa.Uuid, primary_key=True))
    try:
        names = unmapped_tables()
        assert "rt_bare_link" in names
        assert "audit_event" not in names  # a mapped model is never "unmapped"
    finally:
        SQLModel.metadata.remove(link)


def test_references_any_detects_fk_into_owned() -> None:
    from sqlalchemy import Column, ForeignKey, Integer, MetaData, Table

    md = MetaData()
    Table("owned_t", md, Column("id", Integer, primary_key=True))
    linked = Table(
        "link_t", md, Column("o", Integer, ForeignKey("owned_t.id"), primary_key=True)
    )
    lonely = Table("lonely_t", md, Column("id", Integer, primary_key=True))
    assert _references_any(linked, {"owned_t"}) is True
    assert _references_any(lonely, {"owned_t"}) is False


def test_make_fails_closed_on_a_homeless_linked_table(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sqlalchemy as sa
    from sqlalchemy import Column, ForeignKey, Table
    from sqlmodel import SQLModel

    import terp.capabilities.audit.models  # noqa: F401  (audit_event is owned + mapped)

    tree = MigrationTree("audit", "terp.capabilities.audit", tmp_path / "migrations")
    monkeypatch.setattr(orchestrate, "resolve_migration_target", lambda *a, **k: tree)
    # a bare association Table (no mapped class) wired into an owned table by an FK
    link = Table(
        "rt_homeless_link",
        SQLModel.metadata,
        Column("audit_id", sa.Uuid, ForeignKey("audit_event.id"), primary_key=True),
    )
    try:
        with pytest.raises(MigrationError, match="no mapped model"):
            orchestrate.make(
                "audit", "x", f"sqlite:///{tmp_path / 'm.db'}", autogenerate=True
            )
    finally:
        SQLModel.metadata.remove(link)


def test_dependency_edges_maps_foreign_keys_to_owner_labels() -> None:
    from sqlalchemy import Column, ForeignKey, Integer, MetaData, Table

    md = MetaData()
    Table("zzz_t", md, Column("id", Integer, primary_key=True))
    Table(
        "aaa_t",
        md,
        Column("id", Integer, primary_key=True),
        Column("z", Integer, ForeignKey("zzz_t.id")),  # target owned -> edge
        Column("o", Integer, ForeignKey("orphan_t.id")),  # target unowned -> skipped
    )
    Table("orphan_t", md, Column("id", Integer, primary_key=True))  # owned by nobody
    label_of_table = {"zzz_t": "zzz", "aaa_t": "aaa"}  # orphan_t intentionally absent
    edges = _dependency_edges(md, label_of_table)
    assert edges["aaa"] == {"zzz"}
    assert edges["zzz"] == set()


def test_toposort_orders_referenced_before_referencing() -> None:
    # 'aaa' sorts first alphabetically but references 'zzz' -> zzz must migrate first.
    aaa = MigrationTree("aaa", "app.modules.aaa", pathlib.Path("/x/migrations"))
    zzz = MigrationTree("zzz", "app.modules.zzz", pathlib.Path("/y/migrations"))
    ordered = _toposort([aaa, zzz], {"aaa": {"zzz"}, "zzz": set()})
    assert [tree.label for tree in ordered] == ["zzz", "aaa"]


def test_toposort_detects_a_cross_package_cycle() -> None:
    a = MigrationTree("a", "app.modules.a", pathlib.Path("/a/migrations"))
    b = MigrationTree("b", "app.modules.b", pathlib.Path("/b/migrations"))
    with pytest.raises(MigrationError, match="cycle"):
        _toposort([a, b], {"a": {"b"}, "b": {"a"}})


def test_model_modules_includes_a_module_without_revision_files(
    tmp_path: pathlib.Path,
) -> None:
    # alpha has a module directory but no migrations/models at all -> not runnable and
    # not model-bearing, so it is skipped. beta is the target and is still required.
    (tmp_path / "app" / "modules" / "alpha").mkdir(parents=True)
    (tmp_path / "app" / "modules" / "beta").mkdir(parents=True)

    mods = _model_modules("app.modules.beta", str(tmp_path / "app"), "app")

    assert "app.modules.alpha.models" not in mods  # route-only/support sibling
    assert "app.modules.beta.models" in mods  # and the target itself


def test_import_model_module_distinguishes_absent_from_broken(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _import_model_module("rt_missing_optional.models", required=False) is False
    with pytest.raises(MigrationError, match="must define models.py"):
        _import_model_module("rt_missing_required.models", required=True)

    def _broken(_module: str) -> object:
        raise ModuleNotFoundError(
            "No module named 'rt_missing_dependency'", name="rt_missing_dependency"
        )

    monkeypatch.setattr(_runtime.importlib, "import_module", _broken)
    with pytest.raises(ModuleNotFoundError, match="rt_missing_dependency"):
        _import_model_module("rt_existing.models", required=False)


def test_homeless_tables_splits_bare_and_mapped_unowned() -> None:
    from sqlalchemy import Column, ForeignKey, Integer, MetaData, Table

    md = MetaData()
    # owned_t (owned) -> shared_t makes shared_t a mapped-but-unowned FK target (finding 4)
    Table(
        "owned_t",
        md,
        Column("id", Integer, primary_key=True),
        Column("s", Integer, ForeignKey("shared_t.id")),
    )
    Table("shared_t", md, Column("id", Integer, primary_key=True))
    # link_t (unmapped) -> owned_t is a bare homeless association table
    Table(
        "link_t", md, Column("o", Integer, ForeignKey("owned_t.id"), primary_key=True)
    )
    # other_t (mapped) -> owned_t is mapped-but-unowned in the other FK direction
    Table(
        "other_t",
        md,
        Column("id", Integer, primary_key=True),
        Column("o", Integer, ForeignKey("owned_t.id")),
    )
    # unrelated_t shares no foreign key with an owned table -> ignored (no false positive)
    Table("unrelated_t", md, Column("id", Integer, primary_key=True))

    bare, mapped_unowned = _homeless_tables(
        md.tables, {"owned_t"}, frozenset({"owned_t", "shared_t", "other_t"})
    )

    assert bare == ["link_t"]
    assert mapped_unowned == ["other_t", "shared_t"]
    assert "unrelated_t" not in bare and "unrelated_t" not in mapped_unowned


def test_make_fails_closed_on_a_mapped_but_unowned_fk_target(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sqlalchemy as sa
    from sqlalchemy import Column, ForeignKey, Table
    from sqlmodel import SQLModel

    import terp.capabilities.audit.models  # noqa: F401  (audit_event is owned + mapped)

    tree = MigrationTree("audit", "terp.capabilities.audit", tmp_path / "migrations")
    monkeypatch.setattr(orchestrate, "resolve_migration_target", lambda *a, **k: tree)
    # rt_shared is backed by a mapped class (we add it to the mapped set) but no migration
    # package owns it, and it is wired to the owned audit_event by a foreign key -> it
    # would never be created, so make must fail closed with its own distinct error.
    real_mapped = _runtime._mapped_table_names()
    monkeypatch.setattr(
        _runtime, "_mapped_table_names", lambda: real_mapped | {"rt_shared"}
    )
    shared = Table(
        "rt_shared",
        SQLModel.metadata,
        Column("audit_id", sa.Uuid, ForeignKey("audit_event.id"), primary_key=True),
    )
    try:
        with pytest.raises(MigrationError, match="no migration package owns"):
            orchestrate.make(
                "audit", "x", f"sqlite:///{tmp_path / 'm.db'}", autogenerate=True
            )
    finally:
        SQLModel.metadata.remove(shared)


def test_make_cleans_up_empty_versions_on_failure(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A first make creates versions/ (and migrations/); if command.revision then fails,
    # the now-empty directories are rolled back so an empty (falsely "current") history
    # is never left behind.
    tree = MigrationTree("audit", "terp.capabilities.audit", tmp_path / "migrations")
    monkeypatch.setattr(orchestrate, "resolve_migration_target", lambda *a, **k: tree)

    def _boom(*a: object, **k: object) -> None:
        raise RuntimeError("revision failed")

    monkeypatch.setattr(orchestrate.command, "revision", _boom)

    with pytest.raises(RuntimeError, match="revision failed"):
        orchestrate.make(
            "audit", "x", f"sqlite:///{tmp_path / 'm.db'}", autogenerate=False
        )

    assert not (tmp_path / "migrations" / "versions").exists()
    assert not (tmp_path / "migrations").exists()  # the parent we created is gone too


def test_first_revision_resolves_fk_to_a_module_without_migrations(
    tmp_path: pathlib.Path,
) -> None:
    # beta's very first revision references alpha, and alpha has NO migration history yet.
    # make('beta') must still import alpha's models so the FK resolves (autogenerate would
    # otherwise raise NoReferencedTableError), while the scoped filters keep alpha's own
    # table out of beta's revision. Run in a subprocess so the synthetic models never
    # pollute this suite's shared SQLModel registry.
    import os
    import subprocess
    import sys
    import textwrap

    app = tmp_path / "rtapp"
    for name in ("alpha", "beta"):
        (app / "modules" / name).mkdir(parents=True)
    for init in (
        app / "__init__.py",
        app / "modules" / "__init__.py",
        app / "modules" / "alpha" / "__init__.py",
        app / "modules" / "beta" / "__init__.py",
    ):
        init.write_text("", encoding="utf-8")
    (app / "modules" / "alpha" / "models.py").write_text(
        textwrap.dedent(
            """
            from __future__ import annotations
            import uuid
            from sqlmodel import Field, SQLModel

            class Alpha(SQLModel, table=True):
                __tablename__ = "rt_alpha"
                id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
            """
        ),
        encoding="utf-8",
    )
    (app / "modules" / "beta" / "models.py").write_text(
        textwrap.dedent(
            """
            from __future__ import annotations
            import uuid
            from sqlmodel import Field, SQLModel

            class Beta(SQLModel, table=True):
                __tablename__ = "rt_beta"
                id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
                alpha_id: uuid.UUID = Field(foreign_key="rt_alpha.id")
            """
        ),
        encoding="utf-8",
    )

    db_url = f"sqlite:///{(tmp_path / 'fk.db').as_posix()}"
    driver = tmp_path / "drive.py"
    driver.write_text(
        textwrap.dedent(
            f"""
            from terp.migrations import make

            make("beta", "beta init", {db_url!r}, {app.as_posix()!r}, package="rtapp")
            """
        ),
        encoding="utf-8",
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(tmp_path), env.get("PYTHONPATH", "")) if part
    )
    result = subprocess.run(
        [sys.executable, str(driver)],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        env=env,
    )
    assert result.returncode == 0, result.stderr

    versions = list((app / "modules" / "beta" / "migrations" / "versions").glob("*.py"))
    assert len(versions) == 1
    body = versions[0].read_text(encoding="utf-8")
    assert "rt_alpha.id" in body  # the FK to the migration-less module resolved
    assert "create_table('rt_beta'" in body
    assert "create_table('rt_alpha'" not in body  # scoping held: alpha is not emitted


# --------------------------------------------------------------------------- #
# per-module schema layout (ADR 0070) — deterministic fakes; live PostgreSQL
# behavior is proven by the conformance suite's env-gated lane.
# --------------------------------------------------------------------------- #
class _FakeDialect:
    def __init__(self, name: str) -> None:
        self.name = name
        self.default_schema_name = "public"


class _FakeConnection:
    def __init__(self, dialect: str, rows: list[tuple[str, ...]] | None = None) -> None:
        self.dialect = _FakeDialect(dialect)
        self.statements: list[str] = []
        self.commits = 0
        self._rows = rows or []

    def exec_driver_sql(self, statement: str) -> list[tuple[str, ...]]:
        self.statements.append(statement)
        return self._rows

    def commit(self) -> None:
        self.commits += 1

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, *args: object) -> None:
        return None


class _FakeEngine:
    def __init__(self, connection: _FakeConnection, database: str = "appdb") -> None:
        self._connection = connection
        self.url = SimpleNamespace(database=database)
        self.disposed = False

    def connect(self) -> _FakeConnection:
        return self._connection

    def begin(self) -> _FakeConnection:
        # The transactional entry (adopt_schemas): same fake connection, so tests
        # observe the statements regardless of which entry point the code uses.
        return self._connection

    def dispose(self) -> None:
        self.disposed = True


def test_search_path_statement_puts_the_owner_first_and_public_last() -> None:
    statement = _runtime.search_path_statement("notes", ["audit", "notes", "tasks"])
    assert statement == 'SET search_path TO "notes", "audit", "tasks", "public"'


def test_enter_per_module_schema_routes_the_run() -> None:
    connection = _FakeConnection("postgresql")
    _runtime._enter_per_module_schema(connection, "notes", ["audit", "notes"])
    assert connection.statements[0] == 'CREATE SCHEMA IF NOT EXISTS "notes"'
    assert connection.statements[1].startswith('SET search_path TO "notes"')
    # The setup transaction is committed so Alembic owns (and commits) the DDL txn.
    assert connection.commits == 1
    # Reflection is pinned to the package schema (the documented Alembic recipe).
    assert connection.dialect.default_schema_name == "notes"


def test_enter_per_module_schema_fails_closed_off_postgres() -> None:
    with pytest.raises(MigrationError, match="requires PostgreSQL"):
        _runtime._enter_per_module_schema(_FakeConnection("sqlite"), "notes", ["notes"])


def test_run_migrations_applies_the_per_module_layout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The env delegate, driven by a fake context/engine: the per-module branch must
    # create + enter the package schema and pin the version table to public.
    connection = _FakeConnection("postgresql")
    monkeypatch.setattr(
        _runtime, "create_engine", lambda url, **kw: _FakeEngine(connection)
    )
    recorded: dict[str, object] = {}

    class _FakeContext:
        config = SimpleNamespace(
            get_main_option=lambda name: {
                "terp_import_path": "terp.capabilities.audit",
                "terp_version_table": "alembic_version_audit",
                "terp_label": "audit",
                "sqlalchemy.url": "postgresql+psycopg://u:p@h/appdb",
                "terp_app_root": "",
                "terp_package": "app",
                "terp_schema_layout": "per-module",
            }.get(name)
        )

        def configure(self, **kwargs: object) -> None:
            recorded.update(kwargs)

        def is_offline_mode(self) -> bool:
            return False

        def begin_transaction(self) -> _FakeConnection:
            return _FakeConnection("postgresql")

        def run_migrations(self) -> None:
            recorded["ran"] = True

    _runtime.run_migrations(_FakeContext())

    assert recorded["ran"] is True
    assert recorded["version_table_schema"] == "public"
    assert connection.statements[0] == 'CREATE SCHEMA IF NOT EXISTS "audit"'
    assert connection.statements[1].startswith('SET search_path TO "audit"')


def _offline_context(recorded: dict[str, object], layout: str) -> object:
    """An Alembic context faked into offline (--sql) mode for the given layout."""

    class _FakeOfflineContext:
        config = SimpleNamespace(
            get_main_option=lambda name: {
                "terp_import_path": "terp.capabilities.audit",
                "terp_version_table": "alembic_version_audit",
                "terp_label": "audit",
                "sqlalchemy.url": "sqlite:///offline.db",
                "terp_app_root": "",
                "terp_package": "app",
                "terp_schema_layout": layout,
            }.get(name)
        )

        def is_offline_mode(self) -> bool:
            return True

        def configure(self, **kwargs: object) -> None:
            recorded.update(kwargs)

        def begin_transaction(self) -> _FakeConnection:
            return _FakeConnection("sqlite")

        def run_migrations(self) -> None:
            recorded["ran"] = True

    return _FakeOfflineContext()


def test_run_migrations_offline_renders_without_connecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Offline (--sql) mode must never open an engine: Alembic renders from the URL.
    def _no_engine(url: str, **kwargs: object) -> None:
        raise AssertionError("offline mode must not create an engine")

    monkeypatch.setattr(_runtime, "create_engine", _no_engine)
    recorded: dict[str, object] = {}
    _runtime.run_migrations(_offline_context(recorded, "flat"))
    assert recorded["ran"] is True
    assert recorded["url"] == "sqlite:///offline.db"
    assert recorded["literal_binds"] is True


def test_run_migrations_offline_refuses_the_per_module_layout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # search_path is session state a static script cannot carry — fail closed.
    monkeypatch.setattr(
        _runtime, "create_engine", lambda url, **kw: pytest.fail("must not connect")
    )
    with pytest.raises(MigrationError, match="flat layout only"):
        _runtime.run_migrations(_offline_context({}, "per-module"))


def test_database_search_path_statements_route_app_connections() -> None:
    statements = orchestrate.database_search_path_statements("appdb", ["audit", "notes"])
    assert statements[0] == 'CREATE SCHEMA IF NOT EXISTS "audit"'
    assert statements[1] == 'CREATE SCHEMA IF NOT EXISTS "notes"'
    assert statements[2] == (
        'ALTER DATABASE "appdb" SET search_path TO "audit", "notes", "public"'
    )


def test_ensure_database_search_path_executes_and_disposes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _FakeConnection("postgresql")
    engine = _FakeEngine(connection)
    monkeypatch.setattr(orchestrate, "create_engine", lambda url, **kw: engine)
    labels = orchestrate.ensure_database_search_path("postgresql://u:p@h/appdb")
    assert labels  # the installed capabilities' labels
    assert any(stmt.startswith("ALTER DATABASE") for stmt in connection.statements)
    assert engine.disposed is True


def test_ensure_database_search_path_fails_closed_off_postgres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _FakeEngine(_FakeConnection("sqlite"))
    monkeypatch.setattr(orchestrate, "create_engine", lambda url, **kw: engine)
    with pytest.raises(MigrationError, match="requires PostgreSQL"):
        orchestrate.ensure_database_search_path("sqlite://")
    assert engine.disposed is True


def test_adopt_schemas_moves_owned_tables_out_of_public(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # information_schema reports audit_event still flat in public -> exactly that
    # table is moved into the audit schema; version tables never move.
    connection = _FakeConnection(
        "postgresql", rows=[("audit_event",), ("alembic_version_audit",)]
    )
    monkeypatch.setattr(
        orchestrate, "create_engine", lambda url, **kw: _FakeEngine(connection)
    )
    routed: dict[str, object] = {}
    monkeypatch.setattr(
        orchestrate,
        "ensure_database_search_path",
        lambda url, app_root=None, *, package="app": routed.setdefault("url", url),
    )
    moved = orchestrate.adopt_schemas("postgresql://u:p@h/appdb")
    assert moved["audit"] == ["audit_event"]
    assert (
        'ALTER TABLE "public"."audit_event" SET SCHEMA "audit"' in connection.statements
    )
    assert not any("alembic_version" in stmt for stmt in connection.statements if "ALTER TABLE" in stmt)
    assert routed["url"] == "postgresql://u:p@h/appdb"


def test_adopt_schemas_fails_closed_off_postgres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        orchestrate, "create_engine", lambda url, **kw: _FakeEngine(_FakeConnection("sqlite"))
    )
    with pytest.raises(MigrationError, match="requires PostgreSQL"):
        orchestrate.adopt_schemas("sqlite://")


def test_effective_layout_prefers_the_explicit_override() -> None:
    assert orchestrate._effective_layout("per-module") == "per-module"
    # Default: the settings knob (flat in dev/test).
    assert orchestrate._effective_layout(None) == "flat"


# --------------------------------------------------------------------------- #
# runtime role grants (ADR 0071) — deterministic fakes; the live refusal proof
# runs in the conformance suite's PostgreSQL lane.
# --------------------------------------------------------------------------- #
def test_runtime_grant_statements_split_write_and_read_surfaces() -> None:
    statements = orchestrate.runtime_grant_statements(
        "appdb", "terp_rt", write_schemas=["notes"], read_schemas=["public"]
    )
    assert statements[0] == 'GRANT CONNECT ON DATABASE "appdb" TO "terp_rt"'
    joined = "\n".join(statements)
    # Write surface: full DML + sequences + default privileges for future tables.
    assert 'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA "notes"' in joined
    assert 'ALTER DEFAULT PRIVILEGES IN SCHEMA "notes"' in joined
    # Read surface: SELECT only — never INSERT/UPDATE/DELETE on public.
    assert 'GRANT SELECT ON ALL TABLES IN SCHEMA "public" TO "terp_rt"' in joined
    assert 'INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA "public"' not in joined
    # And never any DDL-granting statement at all.
    assert "CREATE" not in joined and "OWNER" not in joined


def test_runtime_grant_statements_scope_defaults_to_the_owner_role() -> None:
    # PostgreSQL applies ALTER DEFAULT PRIVILEGES to objects created by the named
    # role — FOR ROLE pins it to the migration owner when a different admin grants.
    statements = orchestrate.runtime_grant_statements(
        "appdb",
        "terp_rt",
        write_schemas=["notes"],
        read_schemas=["public"],
        owner_role="terp_owner",
    )
    joined = "\n".join(statements)
    assert 'ALTER DEFAULT PRIVILEGES FOR ROLE "terp_owner" IN SCHEMA "notes"' in joined
    assert 'ALTER DEFAULT PRIVILEGES FOR ROLE "terp_owner" IN SCHEMA "public"' in joined
    # Plain GRANTs stay owner-agnostic.
    assert 'GRANT CONNECT ON DATABASE "appdb" TO "terp_rt"' in joined


def test_grant_runtime_role_is_layout_aware(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = _FakeConnection("postgresql")
    monkeypatch.setattr(
        orchestrate, "create_engine", lambda url, **kw: _FakeEngine(connection)
    )
    schemas = orchestrate.grant_runtime_role(
        "postgresql://u:p@h/appdb", "terp_rt", schema_layout="per-module"
    )
    # Per-module: package schemas are the write surface, public is read-only.
    assert "public" in schemas and "audit" in schemas
    joined = "\n".join(connection.statements)
    assert 'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA "audit"' in joined
    assert 'GRANT SELECT ON ALL TABLES IN SCHEMA "public" TO "terp_rt"' in joined

    flat = _FakeConnection("postgresql")
    monkeypatch.setattr(orchestrate, "create_engine", lambda url, **kw: _FakeEngine(flat))
    assert orchestrate.grant_runtime_role(
        "postgresql://u:p@h/appdb", "terp_rt", schema_layout="flat"
    ) == ["public"]
    assert any(
        'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA "public"' in stmt
        for stmt in flat.statements
    )


def test_grant_runtime_role_rejects_a_non_identifier_role() -> None:
    # Role names are interpolated into DDL — anything but a plain identifier
    # fails closed before any connection is opened (runtime AND owner role).
    with pytest.raises(MigrationError, match="plain identifier"):
        orchestrate.grant_runtime_role("postgresql://u:p@h/appdb", 'rt"; DROP ROLE x')
    with pytest.raises(MigrationError, match="owner role"):
        orchestrate.grant_runtime_role(
            "postgresql://u:p@h/appdb", "terp_rt", owner_role="bad owner"
        )


def test_grant_runtime_role_fails_closed_off_postgres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        orchestrate,
        "create_engine",
        lambda url, **kw: _FakeEngine(_FakeConnection("sqlite")),
    )
    with pytest.raises(MigrationError, match="requires PostgreSQL"):
        orchestrate.grant_runtime_role("sqlite://", "terp_rt", schema_layout="flat")


def test_upgrade_routes_the_database_before_migrating_per_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Under the per-module layout, upgrade pins the database-level search_path
    # BEFORE any history runs, so the first created table already routes correctly.
    order: list[str] = []
    monkeypatch.setattr(
        orchestrate,
        "ensure_database_search_path",
        lambda url, app_root=None, *, package="app": order.append("route"),
    )
    monkeypatch.setattr(
        orchestrate.command, "upgrade", lambda config, revision: order.append("migrate")
    )
    applied = orchestrate.upgrade(
        "postgresql://u:p@h/appdb", schema_layout="per-module"
    )
    assert applied  # the installed capabilities' labels
    assert order[0] == "route"
    assert order.count("migrate") == len(applied)
