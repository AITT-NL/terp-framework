"""The fail-closed migration boot guard.

``assert_migrations_current`` is the runtime half of the migration two-layer
control: ``create_app(..., migration_check=assert_migrations_current)`` calls it at
boot (in production) so the app **refuses to start** when any installed package's
database history is behind its code head *or* when a declared package defines table
models but ships no migration history at all. A consumer who deploys a new platform
version without running ``terp migrate upgrade`` gets a loud, safe
:class:`~terp.migrations.errors.PendingMigrationsError` instead of silent breakage
against a stale schema; a module whose table models never got a first revision gets
a :class:`~terp.migrations.errors.MissingMigrationsError` (the runtime half of the
``tables_have_migrations`` rule) instead of serving requests against tables that
were never created. The build-time halves are the upgrade/downgrade conformance
test and the ``terp.arch`` ``tables_have_migrations`` check.
"""

from __future__ import annotations

import pathlib
from collections.abc import Sequence

from alembic import command
from alembic.util import CommandError
from sqlalchemy import Engine, create_engine, inspect

from terp.core.migrations import resolve_all_migration_trees, resolve_migration_trees
from terp.migrations._config import alembic_config_for
from terp.migrations._runtime import (
    _import_model_module,
    _tree_has_models,
    assert_no_split_table_ownership,
    owned_table_names,
)
from terp.migrations.errors import (
    MigrationDriftError,
    MigrationHistoryNotEmptiedError,
    MigrationResidueError,
    MigrationReversibilityError,
    MissingMigrationsError,
    PendingMigrationsError,
)
from terp.migrations.orchestrate import (
    assert_no_orphaned_revisions,
    downgrade,
    migration_status,
    upgrade,
)


def assert_no_missing_histories(
    app_root: str | pathlib.Path | None = None,
    *,
    package: str = "app",
) -> None:
    """Raise :class:`MissingMigrationsError` if a declared package's tables have no history.

    The runtime half of the ``tables_have_migrations`` rule, for the standalone case
    the pending-revisions check cannot see: a package that *declares* migration
    ownership (a capability with a ``terp.migrations`` entry point, or an app module
    under ``<app_root>/modules/<name>``) and defines table models, but ships **no**
    revision script. Its history is never "behind" — it does not exist — so without
    this refusal the tables would silently never be created and the first request
    would fail on a nonexistent table.

    Scoping mirrors the homeless-table check's conservatism, so the guard never
    false-positives on a test fixture: only *declared* trees are examined, a tree
    counts only when it ships a models module, and it is flagged only when a mapped
    table is actually **owned** by its import path in the live metadata. A mapped
    class registered outside every declared tree (e.g. a fixture model) is invisible
    here — that shape stays covered by the FK-scoped homeless-table check at
    ``terp migrate make`` and by the build-time rule.
    """
    missing: list[str] = []
    for tree in resolve_all_migration_trees(app_root, package=package):
        if tree.has_revision_files:
            continue
        if not _tree_has_models(tree):
            continue
        if not _import_model_module(tree.models_module, required=False):
            continue
        if owned_table_names(tree.import_path):
            missing.append(tree.label)
    if missing:
        raise MissingMigrationsError(missing)


def assert_migrations_current(
    engine: Engine,
    app_root: str | pathlib.Path | None = None,
    *,
    package: str = "app",
) -> None:
    """Raise if any package's history is behind head — or missing entirely.

    With no *app_root* only installed capabilities (the platform-shipped histories a
    consumer must apply on upgrade) are checked — exactly the "must run migrations
    for a new version" guarantee. Pass *app_root* to also guard app-module histories.

    Two refusals, fail closed: a package that defines table models but ships **no**
    migration history raises :class:`MissingMigrationsError` (see
    :func:`assert_no_missing_histories` — the runtime half of the
    ``tables_have_migrations`` rule, whose build-time half is the ``terp.arch``
    check), and a declared history that is behind its code head raises
    :class:`PendingMigrationsError`. A database that ran a revision this code no
    longer defines — an applied migration rewritten or deleted — raises
    :class:`~terp.migrations.errors.OrphanedRevisionsError` *before* either, because
    no amount of upgrading will fix it. The FK-scoped homeless-table check (run at
    ``terp migrate make``) additionally catches a mapped-but-unowned table that no
    package would ever create.
    """
    assert_no_missing_histories(app_root, package=package)
    assert_no_orphaned_revisions(
        engine.url.render_as_string(hide_password=False), app_root, package=package
    )
    behind = [
        row.label
        for row in migration_status(engine, app_root, package=package)
        if not row.is_current
    ]
    if behind:
        raise PendingMigrationsError(behind)


def assert_migrations_match_models(
    database_url: str,
    app_root: str | pathlib.Path | None = None,
    *,
    package: str = "app",
    schema_layout: str | None = None,
) -> None:
    """Assert committed migrations exactly match the models (no autogenerate drift).

    The reusable build-time pair to the runtime boot guard, for a *consumer's* test
    suite: upgrade a scratch database to head, then call this — a model changed without
    a regenerated migration raises
    :class:`~terp.migrations.errors.MigrationDriftError`, so the drift is caught in CI,
    not in production. Pass *app_root* to include the app's own modules (not only
    installed capabilities); Terp's own gate runs this over the example app.

    Also fails closed on *split table ownership* — a model whose table another package's
    history creates. Autogenerate cannot see that split (each package's diff is scoped to
    the tables it owns), so it produces no drift of its own; left alone it breaks fresh
    installs only, long after the commit that caused it.

    **One blind spot, and it depends on the database you point this at.** Autogenerate
    compares foreign keys by a signature that includes their referential options
    (``ON DELETE`` / ``ON UPDATE``) *only when the backend reflects those options*.
    PostgreSQL does, so a changed ``ondelete`` shows up as drift there. SQLite does not
    report them at all, so against a SQLite scratch database Alembic falls back to the
    option-less signature and an ``ON DELETE`` clause that changed — or that was never
    chosen — is invisible. A suite that runs this against SQLite is therefore not
    checking referential behaviour; pair it with
    :func:`terp.core.assert_references_declare_delete_behaviour`, which reads the
    declaration on the models and needs no database at all (ADR 0133).
    """
    assert_no_split_table_ownership(
        str(app_root) if app_root is not None else None, package
    )
    drifted: list[str] = []
    for tree in resolve_migration_trees(app_root, package=package):
        try:
            command.check(
                alembic_config_for(
                    tree,
                    database_url,
                    app_root=app_root,
                    package=package,
                    schema_layout=schema_layout,
                )
            )
        except CommandError:
            drifted.append(tree.label)
    if drifted:
        raise MigrationDriftError(drifted)




#: How to read a schema back out of the database's OWN catalogue, per dialect.
#:
#: Never through the SQLAlchemy inspector, and that is the whole point of the helper.
#: Reflection is exactly the layer that loses the two things a batch rebuild loses — a
#: partial index's ``WHERE`` predicate and a CHECK constraint's text — so a check built
#: on it would be blind to the failure it exists to catch, and green.
#:
#: Each entry is a tuple of ``(key, definition)`` queries. Keeping the dialect
#: difference as DATA rather than as a branch means one executor runs everywhere: the
#: code path is identical on both verified dialects, so it cannot work on the one the
#: gate happens to run and rot on the one the app deploys to.
_CATALOGUE_QUERIES: dict[str, tuple[str, ...]] = {
    # sqlite_master.sql is the CREATE statement as written, verbatim.
    "sqlite": (
        "SELECT type || ' ' || name, sql FROM sqlite_master"
        " WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite\\_%' ESCAPE '\\'"
        " ORDER BY type, name",
    ),
    # PostgreSQL has no single verbatim DDL, so it is read back in three pieces —
    # pg_get_indexdef and pg_get_constraintdef are the server's own renderers, which
    # is what makes them faithful where reflection is not.
    "postgresql": (
        "SELECT 'column ' || table_name || '.' || column_name,"
        " data_type || ' null=' || is_nullable"
        " || ' default=' || coalesce(column_default, '-')"
        " || ' len=' || coalesce(character_maximum_length::text, '-')"
        " FROM information_schema.columns"
        " WHERE table_schema = current_schema() ORDER BY 1",
        "SELECT 'index ' || indexname, indexdef FROM pg_indexes"
        " WHERE schemaname = current_schema() ORDER BY 1",
        "SELECT 'constraint ' || conrelid::regclass::text || '.' || conname,"
        " pg_get_constraintdef(oid) FROM pg_constraint"
        " WHERE connamespace = current_schema()::regnamespace ORDER BY 1",
    ),
}


def _catalogue_queries_for(dialect: str) -> tuple[str, ...]:
    """The catalogue queries for *dialect*, or a refusal naming what is supported.

    Fails closed rather than returning an empty snapshot: two empty snapshots compare
    equal, so an unsupported dialect would make this check pass by knowing nothing.
    """
    try:
        return _CATALOGUE_QUERIES[dialect]
    except KeyError:
        raise ValueError(
            f"assert_migrations_reverse_cleanly cannot read the schema catalogue of "
            f"{dialect!r}. The verified dialects are "
            f"{', '.join(sorted(_CATALOGUE_QUERIES))} (ADR 0069)."
        ) from None


def _normalise_constraint_order(definition: str) -> str:
    """Sort the trailing ``CONSTRAINT`` run of a ``CREATE TABLE``; change nothing else.

    A table rebuilt by batch mode emits its table-level constraints in whatever order
    reflection handed them back, which is not stable across two upgrades in one process
    and carries no meaning. Column order does, and is left exactly as found.

    Deliberately the only normalisation. Every other difference between the two
    snapshots is a real difference, and a helper that tidied them away would be a
    rollback check that reports success for a rollback that changed the schema.
    """
    opening = definition.find("(")
    if not definition.lstrip().upper().startswith("CREATE TABLE") or opening == -1:
        return definition
    closing = definition.rfind(")")
    if closing < opening:
        return definition  # pragma: no cover - a CREATE TABLE always closes its list

    head, body, tail = (
        definition[: opening + 1],
        definition[opening + 1 : closing],
        definition[closing:],
    )
    items, depth, current = [], 0, []
    for char in body:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and depth == 0:
            items.append("".join(current))
            current = []
            continue
        current.append(char)
    items.append("".join(current))

    columns = [item for item in items if not item.strip().upper().startswith("CONSTRAINT")]
    constraints = sorted(
        item for item in items if item.strip().upper().startswith("CONSTRAINT")
    )
    return head + ",".join([*columns, *constraints]) + tail


def _schema_snapshot(database_url: str) -> dict[str, str]:
    """Every schema object the database itself reports, by name, as the server renders it."""
    engine = create_engine(database_url)
    try:
        snapshot: dict[str, str] = {}
        with engine.connect() as connection:
            for query in _catalogue_queries_for(engine.dialect.name):
                for key, definition in connection.exec_driver_sql(query).all():
                    snapshot[str(key)] = _normalise_constraint_order(str(definition))
        return snapshot
    finally:
        engine.dispose()


def _applied_revision_labels(database_url: str, labels: Sequence[str]) -> list[str]:
    """The labels whose ``alembic_version_<label>`` table still holds a revision."""
    engine = create_engine(database_url)
    try:
        still_applied: list[str] = []
        existing = set(inspect(engine).get_table_names())
        with engine.connect() as connection:
            for label in labels:
                table = f"alembic_version_{label}"
                if table not in existing:
                    continue
                count = connection.exec_driver_sql(
                    f'SELECT COUNT(*) FROM "{table}"'  # noqa: S608 - a label, not input
                ).scalar_one()
                if count:
                    still_applied.append(label)
        return still_applied
    finally:
        engine.dispose()


def assert_migrations_reverse_cleanly(
    database_url: str,
    app_root: str | pathlib.Path | None = None,
    *,
    package: str = "app",
    schema_layout: str | None = None,
) -> None:
    """Assert the whole history goes down to base and comes back to the same schema.

    The reverse-direction counterpart to :func:`assert_migrations_match_models`, for a
    consumer's own test suite. Every Terp app's rollback plan is
    ``terp migrate downgrade``, and the catalogued ``alembic_downgrades_not_empty`` rule
    proves only that the ``downgrade()`` body is not a lone ``pass`` — a source-level
    check that cannot see a downgrade which dies on its first statement, and cannot see
    one that runs green and comes back with a different schema.

    What it catches, in the order they actually happen:

    * a downgrade that **cannot run** — a constraint, index or column named wrongly in
      the reverse direction. This is the common one, and batch mode makes it easy to get
      wrong because it re-applies the naming convention, so a fully-qualified name
      written by hand dies with "no such constraint";
    * a downgrade that **leaves residue** — a table, index, trigger or view it forgot to
      drop. This is the one the empty-stub rule most looks like it covers and cannot,
      and it is quiet: nothing errors, and the cycle usually converges back to the same
      schema, so it is caught by looking at the MIDDLE rather than at the two ends;
    * a history that **never went down**, which the version-table check catches before
      the second upgrade can hide it;
    * anything else that makes the second upgrade produce a different schema from the
      first.

    **What it cannot catch, stated plainly, because a check whose limits are unwritten
    gets read as covering everything.** This walks the history down and up again, so a
    defect that both walks share is invisible to it — in particular a *forward* batch
    rebuild that drops a partial index's ``WHERE`` predicate, since the rebuild happens
    identically on the way back and both snapshots agree. That class is
    :func:`assert_migrations_match_models`' (autogenerate against the models), and on
    SQLite even that is partly blind, which is why the two belong in the same suite
    rather than one standing in for the other.

    Point it at whichever dialect you have. On SQLite it exercises batch mode; on
    PostgreSQL it exercises native ``ALTER`` and the constraint names the server will
    actually accept — the two fail differently, so a suite that runs only one is proving
    the reverse direction for a dialect it may never deploy to. ``terp_db_url`` from
    ``terp.core.testing`` runs a test on both.

    Runs: upgrade to head, snapshot, downgrade to base, check every package's history
    emptied, upgrade again, snapshot, compare. Destructive by construction — give it a
    scratch database, never one holding anything you want to keep.
    """
    applied = upgrade(
        database_url, app_root, package=package, schema_layout=schema_layout
    )
    before = _schema_snapshot(database_url)

    downgrade(database_url, app_root, package=package, schema_layout=schema_layout)

    # BOTH checks below look at the MIDDLE of the cycle, and that is the whole reason
    # they exist. The second upgrade re-stamps every version table and rebuilds every
    # dropped object, so a history that never went down and one that went down and came
    # back are indistinguishable once it has run — and a down-and-up cycle usually
    # converges to the same schema even when the downgrade left things behind, so
    # comparing the two ends does not find that either.
    still_applied = _applied_revision_labels(database_url, applied)
    if still_applied:
        raise MigrationHistoryNotEmptiedError(still_applied)

    leftovers = sorted(
        key
        for key in _schema_snapshot(database_url)
        if not key.split()[-1].startswith("alembic_version_")
    )
    if leftovers:
        raise MigrationResidueError(leftovers)

    upgrade(database_url, app_root, package=package, schema_layout=schema_layout)
    after = _schema_snapshot(database_url)

    differences = [
        f"{key}: {before.get(key, '<absent>')} | {after.get(key, '<absent>')}"
        for key in sorted(set(before) | set(after))
        if before.get(key) != after.get(key)
    ]
    if differences:
        raise MigrationReversibilityError(differences)


__all__ = [
    "assert_migrations_current",
    "assert_migrations_match_models",
    "assert_migrations_reverse_cleanly",
    "assert_no_missing_histories",
]
