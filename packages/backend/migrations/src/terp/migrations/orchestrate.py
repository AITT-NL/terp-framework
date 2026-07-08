"""Orchestrate Alembic across every discovered package's independent history.

``terp migrate upgrade`` runs each package's ``upgrade head`` in turn (ordered so a
package referenced by a cross-module foreign key is created before the package that
references it); ``downgrade`` reverses that order; ``make`` authors a new revision for
one package; ``stamp``
baselines an existing database; ``heads`` / ``merge_heads`` surface and resolve a
package whose own history diverged; and :func:`migration_status` reports, per package,
where the database sits versus the code head. Each package is a plain, *linear*
Alembic history with its own version table — there is no shared multi-branch graph, so
packages never branch across one another; the only divergence is *within* a single
package (two developers off one head), resolved by ``merge_heads`` (ADR 0027).
"""

from __future__ import annotations

import io
import pathlib
import re
from dataclasses import dataclass

from alembic import command
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine
from sqlalchemy.pool import NullPool

from terp.core import get_settings
from terp.core.migrations import (
    MigrationTree,
    resolve_all_migration_trees,
    resolve_migration_target,
    resolve_migration_trees,
)
from terp.migrations._config import alembic_config_for
from terp.migrations._runtime import (
    _import_model_module,
    assert_no_homeless_tables,
    order_trees_by_dependencies,
    owned_table_names,
)
from terp.migrations.errors import MigrationError


def _effective_layout(schema_layout: str | None) -> str:
    """The layout to apply: an explicit override, else ``settings.DB_SCHEMA_LAYOUT``."""
    return schema_layout if schema_layout is not None else get_settings().DB_SCHEMA_LAYOUT


def database_search_path_statements(database: str, labels: list[str]) -> list[str]:
    """The one-time DDL routing an app's *connections* under the per-module layout.

    ``CREATE SCHEMA`` per package, then ``ALTER DATABASE … SET search_path`` — the
    database itself serves every future connection (the app engine, ``psql``, a BI
    tool) a search_path that resolves each package's unqualified table names, so
    ``terp.core`` needs no knowledge of the layout at all (layer-0 stays clean;
    ADR 0070). ``public`` stays last for shared objects and the pinned
    ``alembic_version_*`` tables.
    """
    joined = ", ".join(f'"{label}"' for label in labels)
    return [
        *[f'CREATE SCHEMA IF NOT EXISTS "{label}"' for label in labels],
        f'ALTER DATABASE "{database}" SET search_path TO {joined}, "public"',
    ]


def ensure_database_search_path(
    database_url: str,
    app_root: str | pathlib.Path | None = None,
    *,
    package: str = "app",
) -> list[str]:
    """Create every package schema and pin the database-level search_path (ADR 0070).

    Runs on the per-module layout path of :func:`upgrade` / :func:`adopt_schemas`;
    idempotent, so re-running an upgrade is safe. Returns the labels routed.
    """
    labels = [
        tree.label for tree in resolve_all_migration_trees(app_root, package=package)
    ]
    engine = create_engine(database_url, poolclass=NullPool, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            if connection.dialect.name != "postgresql":
                raise MigrationError(
                    "schema layout 'per-module' requires PostgreSQL; got dialect "
                    f"{connection.dialect.name!r} (ADR 0070)"
                )
            database = engine.url.database or ""
            for statement in database_search_path_statements(database, labels):
                connection.exec_driver_sql(statement)
    finally:
        engine.dispose()
    return labels


def adopt_schemas(
    database_url: str,
    app_root: str | pathlib.Path | None = None,
    *,
    package: str = "app",
) -> dict[str, list[str]]:
    """Move an existing *flat* database's tables into per-module schemas (one-time).

    The brownfield half of ADR 0070 (the ``stamp`` analogue for layout): each
    package's owned tables still sitting in ``public`` are ``ALTER TABLE … SET
    SCHEMA``-moved into the package's schema — data, indexes, and constraints move
    with the table; the ``alembic_version_*`` tables deliberately stay in ``public``.
    **All-or-nothing:** every move runs in one transaction, so a mid-run failure
    (lock timeout, permissions) rolls the whole adoption back instead of leaving a
    half-mixed layout. Idempotent: a table already moved (or not yet created) is
    skipped. Finishes by pinning the database-level search_path so existing
    connections' unqualified queries keep resolving. Returns ``{label: [moved…]}``.
    """
    trees = resolve_all_migration_trees(app_root, package=package)
    for tree in trees:
        _import_model_module(tree.models_module, required=False)
    engine = create_engine(database_url, poolclass=NullPool)
    moved: dict[str, list[str]] = {}
    try:
        with engine.begin() as connection:
            if connection.dialect.name != "postgresql":
                raise MigrationError(
                    "adopt-schemas requires PostgreSQL; got dialect "
                    f"{connection.dialect.name!r} (ADR 0070)"
                )
            rows = connection.exec_driver_sql(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public'"
            )
            in_public = {row[0] for row in rows}
            for tree in trees:
                connection.exec_driver_sql(f'CREATE SCHEMA IF NOT EXISTS "{tree.label}"')
                movable = sorted(owned_table_names(tree.import_path) & in_public)
                for table in movable:
                    connection.exec_driver_sql(
                        f'ALTER TABLE "public"."{table}" SET SCHEMA "{tree.label}"'
                    )
                if movable:
                    moved[tree.label] = movable
    finally:
        engine.dispose()
    ensure_database_search_path(database_url, app_root, package=package)
    return moved


_ROLE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def runtime_grant_statements(
    database: str,
    role: str,
    *,
    write_schemas: list[str],
    read_schemas: list[str],
    owner_role: str | None = None,
) -> list[str]:
    """The least-privilege grant set for an app *runtime* role (ADR 0071).

    The runtime role gets exactly the DML the audited service layer needs —
    SELECT/INSERT/UPDATE/DELETE plus sequence usage — on the *write* schemas, and
    read-only SELECT on the *read* schemas. ``ALTER DEFAULT PRIVILEGES`` extends the
    same grants to tables created later; pass *owner_role* (the role that runs
    ``terp migrate``) to scope those defaults with ``FOR ROLE`` when the grantor is
    a different (e.g. DBA) role — PostgreSQL applies default privileges only to
    objects created by the named role, so without it the defaults cover only the
    executing role's future tables. No CREATE, no ownership, no DDL: a compromised
    app process cannot alter, drop, or create a table — the database itself refuses.

    Deliberately **not** module-to-module isolation: one runtime role holds DML on
    every write schema, because audit and outbox rows ride the business write's
    single session (ADR 0007 / 0045) — cross-module DML stays code-enforced
    (``no_cross_module_imports``, service-only writes), never database-enforced.
    """
    for_owner = f'FOR ROLE "{owner_role}" ' if owner_role else ""
    statements = [f'GRANT CONNECT ON DATABASE "{database}" TO "{role}"']
    for schema in [*write_schemas, *read_schemas]:
        statements.append(f'GRANT USAGE ON SCHEMA "{schema}" TO "{role}"')
    for schema in write_schemas:
        statements.extend(
            [
                f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA "{schema}" '
                f'TO "{role}"',
                f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA "{schema}" TO "{role}"',
                f'ALTER DEFAULT PRIVILEGES {for_owner}IN SCHEMA "{schema}" '
                f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "{role}"',
                f'ALTER DEFAULT PRIVILEGES {for_owner}IN SCHEMA "{schema}" '
                f'GRANT USAGE, SELECT ON SEQUENCES TO "{role}"',
            ]
        )
    for schema in read_schemas:
        statements.extend(
            [
                f'GRANT SELECT ON ALL TABLES IN SCHEMA "{schema}" TO "{role}"',
                f'ALTER DEFAULT PRIVILEGES {for_owner}IN SCHEMA "{schema}" '
                f'GRANT SELECT ON TABLES TO "{role}"',
            ]
        )
    return statements


def grant_runtime_role(
    database_url: str,
    role: str,
    app_root: str | pathlib.Path | None = None,
    *,
    package: str = "app",
    schema_layout: str | None = None,
    owner_role: str | None = None,
) -> list[str]:
    """Grant least-privilege DML to an *existing* runtime login role (ADR 0071).

    The Tier-2 privilege split: migrations run as the owning (DDL-capable) role;
    the app connects as *role*, which this grants exactly the DML surface and
    nothing else. Terp never creates the login or touches its password — the
    operator provisions credentials; this command only shapes privileges, so no
    secret ever rides an argv or a SQL literal in our logs.

    Run it as the same role that runs ``terp migrate`` — or pass *owner_role* to
    name that role explicitly (``ALTER DEFAULT PRIVILEGES FOR ROLE``), so tables
    created by future upgrades are covered no matter which admin ran the grant.

    Layout-aware: under ``per-module`` the package schemas are writable and
    ``public`` becomes **read-only** — the app can read the ``alembic_version_*``
    tables (the boot guard) but can no longer tamper with migration state. Under
    ``flat`` every table lives in ``public``, so ``public`` is the write surface
    (and version-table tampering remains possible — one more reason to adopt the
    layout). Run it *after* ``upgrade`` / ``adopt-schemas``: granting on a schema
    that does not exist yet fails loudly rather than silently skipping.
    """
    for name, kind in ((role, "runtime role"), (owner_role, "owner role")):
        if name is not None and not _ROLE_NAME_RE.match(name):
            raise MigrationError(
                f"{kind} name {name!r} is not a plain identifier "
                "([A-Za-z_][A-Za-z0-9_]*); pick a simple role name"
            )
    layout = _effective_layout(schema_layout)
    if layout == "per-module":
        labels = [
            tree.label for tree in resolve_all_migration_trees(app_root, package=package)
        ]
        write_schemas, read_schemas = labels, ["public"]
    else:
        write_schemas, read_schemas = ["public"], []
    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with engine.begin() as connection:
            if connection.dialect.name != "postgresql":
                raise MigrationError(
                    "grant-runtime requires PostgreSQL; got dialect "
                    f"{connection.dialect.name!r} (ADR 0071)"
                )
            database = engine.url.database or ""
            for statement in runtime_grant_statements(
                database,
                role,
                write_schemas=write_schemas,
                read_schemas=read_schemas,
                owner_role=owner_role,
            ):
                connection.exec_driver_sql(statement)
    finally:
        engine.dispose()
    return [*write_schemas, *read_schemas]


def upgrade(
    database_url: str,
    app_root: str | pathlib.Path | None = None,
    *,
    package: str = "app",
    revision: str = "head",
    schema_layout: str | None = None,
) -> list[str]:
    """Upgrade every discovered package to *revision* (default its head). Returns labels."""
    layout = _effective_layout(schema_layout)
    if layout == "per-module":
        ensure_database_search_path(database_url, app_root, package=package)
    applied: list[str] = []
    for tree in order_trees_by_dependencies(
        resolve_migration_trees(app_root, package=package)
    ):
        command.upgrade(
            alembic_config_for(
                tree,
                database_url,
                app_root=app_root,
                package=package,
                schema_layout=layout,
            ),
            revision,
        )
        applied.append(tree.label)
    return applied


def upgrade_sql(
    database_url: str,
    app_root: str | pathlib.Path | None = None,
    *,
    package: str = "app",
    revision: str = "head",
    schema_layout: str | None = None,
) -> str:
    """Render ``upgrade`` as an offline SQL script (Alembic ``--sql`` mode); connect nothing.

    For DBA-gated deployments where the migration runner may not touch production:
    each package's history is rendered in the same FK-dependency order ``upgrade``
    applies it, under a per-package header comment, with the
    ``alembic_version_<label>`` bookkeeping statements included — so a database the
    DBA builds from the script still reports *current* to ``status`` and the boot
    guard. The URL supplies only the dialect; no connection is ever opened. Flat
    layout only: the per-module layout routes DDL through session state
    (``search_path``) that a static script cannot carry faithfully, so it fails
    closed rather than render SQL that would land tables in the wrong schema
    (ADR 0072). Target a server dialect: SQLite is not renderable offline once a
    history carries an ALTER (batch mode needs live reflection — Alembic's own
    loud ``CommandError``), and the DBA workflow this serves is a server database.
    """
    layout = _effective_layout(schema_layout)
    if layout == "per-module":
        raise MigrationError(
            "offline SQL (--sql) supports the flat layout only; a per-module "
            "database migrates online (`terp migrate upgrade`) so the layout's "
            "session state routes each package's DDL (ADR 0072)"
        )
    chunks: list[str] = []
    for tree in order_trees_by_dependencies(
        resolve_migration_trees(app_root, package=package)
    ):
        buffer = io.StringIO()
        config = alembic_config_for(
            tree,
            database_url,
            app_root=app_root,
            package=package,
            schema_layout=layout,
        )
        config.output_buffer = buffer
        command.upgrade(config, revision, sql=True)
        chunks.append(f"-- terp migrate: {tree.label}\n{buffer.getvalue()}")
    return "\n".join(chunks)


def downgrade(
    database_url: str,
    app_root: str | pathlib.Path | None = None,
    *,
    package: str = "app",
    revision: str = "base",
    label: str | None = None,
    schema_layout: str | None = None,
) -> list[str]:
    """Downgrade to *revision*: one package when *label* is given, else every package.

    A concrete revision hash exists in only one package's history, so the all-package
    form accepts only globally-meaningful targets — ``base`` or a relative ``-N`` — and
    rejects a package-specific hash (which would fail for, or be wrongly applied to,
    the others). Pass *label* to downgrade a single package to any of its own
    revisions. Packages are reversed for a safe teardown order.
    """
    layout = _effective_layout(schema_layout)
    if label is not None:
        tree = resolve_migration_target(label, app_root, package=package)
        command.downgrade(
            alembic_config_for(
                tree,
                database_url,
                app_root=app_root,
                package=package,
                schema_layout=layout,
            ),
            revision,
        )
        return [tree.label]
    if not _is_global_revision(revision):
        raise MigrationError(
            f"downgrade revision {revision!r} is package-specific; pass label=... to "
            "target one package, or use 'base' or a relative '-N' (which apply to every "
            "package)"
        )
    reverted: list[str] = []
    ordered = order_trees_by_dependencies(
        resolve_migration_trees(app_root, package=package)
    )
    for tree in reversed(ordered):
        command.downgrade(
            alembic_config_for(
                tree,
                database_url,
                app_root=app_root,
                package=package,
                schema_layout=layout,
            ),
            revision,
        )
        reverted.append(tree.label)
    return reverted


def _is_global_revision(revision: str) -> bool:
    """A downgrade target meaningful for every package: ``base`` or relative ``-N``."""
    return revision == "base" or (revision.startswith("-") and revision[1:].isdigit())


def make(
    label: str,
    message: str,
    database_url: str,
    app_root: str | pathlib.Path | None = None,
    *,
    package: str = "app",
    autogenerate: bool = True,
    schema_layout: str | None = None,
) -> MigrationTree:
    """Author a new revision for the package *label* (autogenerated by default).

    Creates the package's ``versions/`` directory on the first revision, then runs
    Alembic ``revision`` against *database_url* (autogenerate diffs the live database
    against the package's owned tables). If authoring that first revision fails after
    the directory was created, the now-empty directory is removed again, so a failed
    ``make`` never leaves an empty ``versions/`` behind — which would otherwise be
    mistaken for an (empty, falsely "current") runnable history.
    """
    tree = resolve_migration_target(label, app_root, package=package)
    if autogenerate:
        resolved_root = str(app_root) if app_root is not None else None
        assert_no_homeless_tables(tree, resolved_root, package)
    versions = tree.versions_path
    created = [path for path in (versions.parent, versions) if not path.exists()]
    versions.mkdir(parents=True, exist_ok=True)
    try:
        command.revision(
            alembic_config_for(
                tree,
                database_url,
                app_root=app_root,
                package=package,
                schema_layout=_effective_layout(schema_layout),
            ),
            message=message,
            autogenerate=autogenerate,
        )
    except BaseException:
        for path in reversed(created):
            if path.is_dir() and not any(path.iterdir()):
                path.rmdir()
        raise
    return tree


def stamp(
    database_url: str,
    app_root: str | pathlib.Path | None = None,
    *,
    package: str = "app",
    revision: str = "head",
    schema_layout: str | None = None,
) -> list[str]:
    """Stamp every package's version table to *revision* without running any DDL.

    The brownfield-adoption seam: when a database already has the schema (e.g. built by
    an earlier ``create_all`` or a hand-rolled deploy), stamping records each package's
    history at *revision* (default its head) so the ``alembic_version_<label>`` tables
    exist and a later ``upgrade`` applies only genuinely new migrations — no existing
    table is recreated, no data is dropped.
    """
    layout = _effective_layout(schema_layout)
    stamped: list[str] = []
    for tree in resolve_migration_trees(app_root, package=package):
        command.stamp(
            alembic_config_for(
                tree,
                database_url,
                app_root=app_root,
                package=package,
                schema_layout=layout,
            ),
            revision,
        )
        stamped.append(tree.label)
    return stamped


def heads(
    database_url: str,
    app_root: str | pathlib.Path | None = None,
    *,
    package: str = "app",
) -> dict[str, list[str]]:
    """Per-package head revisions; more than one means that package's history diverged."""
    result: dict[str, list[str]] = {}
    for tree in resolve_migration_trees(app_root, package=package):
        script = ScriptDirectory.from_config(
            alembic_config_for(tree, database_url, app_root=app_root, package=package)
        )
        result[tree.label] = list(script.get_heads())
    return result


def merge_heads(
    label: str,
    message: str,
    database_url: str,
    app_root: str | pathlib.Path | None = None,
    *,
    package: str = "app",
) -> MigrationTree:
    """Merge package *label*'s multiple heads into one, restoring a single linear head.

    Independent per-package histories remove cross-package branching, but two
    developers authoring on divergent branches still produce *within*-package multiple
    heads. This is the first-class remedy: a merge revision is written into the
    package's own ``versions/`` so ``upgrade`` resolves again — without the consumer
    having to rebuild the Alembic config to run ``alembic merge`` by hand.
    """
    tree = resolve_migration_target(label, app_root, package=package)
    config = alembic_config_for(tree, database_url, app_root=app_root, package=package)
    revisions = list(ScriptDirectory.from_config(config).get_heads())
    if len(revisions) < 2:
        raise MigrationError(
            f"package {label!r} has {len(revisions)} head(s); merge needs at least two"
        )
    command.merge(config, revisions=revisions, message=message)
    return tree


@dataclass(frozen=True)
class MigrationStatus:
    """Where one package's database history sits versus its code head."""

    label: str
    current: str | None
    head: str | None

    @property
    def is_current(self) -> bool:
        """True when the database is at the package's code head (nothing pending)."""
        return self.current == self.head


def migration_status(
    engine: Engine,
    app_root: str | pathlib.Path | None = None,
    *,
    package: str = "app",
) -> list[MigrationStatus]:
    """Per-package current-vs-head status, read through *engine* (no schema change)."""
    database_url = engine.url.render_as_string(hide_password=False)
    rows: list[MigrationStatus] = []
    for tree in resolve_migration_trees(app_root, package=package):
        script = ScriptDirectory.from_config(
            alembic_config_for(tree, database_url, app_root=app_root, package=package)
        )
        head = script.get_current_head()
        with engine.connect() as connection:
            context = MigrationContext.configure(
                connection, opts={"version_table": tree.version_table}
            )
            current = context.get_current_revision()
        rows.append(MigrationStatus(label=tree.label, current=current, head=head))
    return rows


__all__ = [
    "MigrationStatus",
    "adopt_schemas",
    "database_search_path_statements",
    "downgrade",
    "ensure_database_search_path",
    "grant_runtime_role",
    "heads",
    "make",
    "merge_heads",
    "migration_status",
    "runtime_grant_statements",
    "stamp",
    "upgrade",
    "upgrade_sql",
]
