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

from alembic import command
from alembic.util import CommandError
from sqlalchemy import Engine

from terp.core.migrations import resolve_all_migration_trees, resolve_migration_trees
from terp.migrations._config import alembic_config_for
from terp.migrations._runtime import (
    _import_model_module,
    _tree_has_models,
    owned_table_names,
)
from terp.migrations.errors import (
    MigrationDriftError,
    MissingMigrationsError,
    PendingMigrationsError,
)
from terp.migrations.orchestrate import migration_status


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
    :class:`PendingMigrationsError`. The FK-scoped homeless-table check (run at
    ``terp migrate make``) additionally catches a mapped-but-unowned table that no
    package would ever create.
    """
    assert_no_missing_histories(app_root, package=package)
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
    """
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


__all__ = [
    "assert_migrations_current",
    "assert_migrations_match_models",
    "assert_no_missing_histories",
]
