"""The fail-closed pending-migrations boot guard.

``assert_migrations_current`` is the runtime half of the migration two-layer
control: ``create_app(..., migration_check=assert_migrations_current)`` calls it at
boot (in production) so the app **refuses to start** when any installed package's
database history is behind its code head. A consumer who deploys a new platform
version without running ``terp migrate upgrade`` gets a loud, safe
:class:`~terp.migrations.errors.PendingMigrationsError` instead of silent breakage
against a stale schema. The build-time half is the upgrade/downgrade conformance
test.
"""

from __future__ import annotations

import pathlib

from alembic import command
from alembic.util import CommandError
from sqlalchemy import Engine

from terp.core.migrations import resolve_migration_trees
from terp.migrations._config import alembic_config_for
from terp.migrations.errors import MigrationDriftError, PendingMigrationsError
from terp.migrations.orchestrate import migration_status


def assert_migrations_current(
    engine: Engine,
    app_root: str | pathlib.Path | None = None,
    *,
    package: str = "app",
) -> None:
    """Raise :class:`PendingMigrationsError` if any package's history is behind head.

    With no *app_root* only installed capabilities (the platform-shipped histories a
    consumer must apply on upgrade) are checked — exactly the "must run migrations
    for a new version" guarantee. Pass *app_root* to also guard app-module histories.

    Scope: this checks only **declared** histories — a capability with a
    ``terp.migrations`` entry point or an app module that ships a ``migrations/``
    directory. A module that defines a table model but ships *no* migration is
    invisible here (it has no history to be "behind"), so its table would simply be
    missing. That gap is closed at build time by the ``terp.arch``
    ``tables_have_migrations`` rule (every app module with a table model must ship a
    migration), the static complement to this runtime guard; the
    ``unowned_tables`` / homeless-table check (run at ``terp migrate make``) catches a
    mapped-but-unowned table that no package would ever create.
    """
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


__all__ = ["assert_migrations_current", "assert_migrations_match_models"]
