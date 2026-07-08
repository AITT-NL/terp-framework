"""terp.migrations — Alembic integration for independent per-package histories.

Each table-owning package (capability or app module) owns a **linear** Alembic
history with its own ``alembic_version_<label>`` table; ``terp migrate`` discovers
and orchestrates them through the pure :mod:`terp.core.migrations` seam (ADR 0027).
There is no shared multi-branch graph, so packages never branch across one another; a
*within*-package divergence (two developers off one head) is the only kind, surfaced
by ``terp migrate heads`` and resolved by ``terp migrate merge``. The fail-closed
:func:`assert_migrations_current` boot guard (wired via
``create_app(migration_check=...)``) makes "the consumer must migrate for a new
version" an enforced guarantee, not a hope.

The kernel (:mod:`terp.core`) never imports this package, keeping Alembic out of the
layer-0 boundary.
"""

from __future__ import annotations

from terp.migrations._runtime import unmapped_tables, unowned_tables
from terp.migrations.cli import migrate_main
from terp.migrations.errors import (
    MigrationDriftError,
    MigrationError,
    PendingMigrationsError,
)
from terp.migrations.guard import (
    assert_migrations_current,
    assert_migrations_match_models,
)
from terp.migrations.orchestrate import (
    MigrationStatus,
    adopt_schemas,
    downgrade,
    ensure_database_search_path,
    grant_runtime_role,
    heads,
    make,
    merge_heads,
    migration_status,
    stamp,
    upgrade,
    upgrade_sql,
)

__all__ = [
    "MigrationDriftError",
    "MigrationError",
    "MigrationStatus",
    "PendingMigrationsError",
    "adopt_schemas",
    "assert_migrations_current",
    "assert_migrations_match_models",
    "downgrade",
    "ensure_database_search_path",
    "grant_runtime_role",
    "heads",
    "make",
    "merge_heads",
    "migrate_main",
    "migration_status",
    "stamp",
    "unmapped_tables",
    "unowned_tables",
    "upgrade",
    "upgrade_sql",
]
