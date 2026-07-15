"""Typed errors for the migration subsystem."""

from __future__ import annotations

from collections.abc import Sequence


class MigrationError(RuntimeError):
    """A migration operation failed (base class)."""


class PendingMigrationsError(MigrationError):
    """The database is behind the code: one or more package histories are not at head.

    Raised by :func:`terp.migrations.assert_migrations_current` (the fail-closed boot
    guard ``create_app`` can install) so an app refuses to serve against an
    un-migrated schema — the consumer must run ``terp migrate upgrade`` after pulling
    a new platform version. The behind packages are named so the fix is obvious.
    """

    def __init__(self, behind: Sequence[str]) -> None:
        self.behind = tuple(behind)
        joined = ", ".join(self.behind)
        super().__init__(
            f"database schema is behind the code for: {joined}. Run "
            f"`terp migrate upgrade` to apply pending migrations before starting the app."
        )


class MissingMigrationsError(MigrationError):
    """A declared package defines table models but ships no migration history at all.

    Raised by :func:`terp.migrations.assert_no_missing_histories` (run by the
    :func:`terp.migrations.assert_migrations_current` boot guard) — the runtime half
    of the ``tables_have_migrations`` rule. Such a package is invisible to the
    pending-revisions check (it has no history to be "behind"), so without this
    refusal its tables would silently never be created and the first request would
    fail on a nonexistent table. The packages are named so the fix is obvious.
    """

    def __init__(self, missing: Sequence[str]) -> None:
        self.missing = tuple(missing)
        joined = ", ".join(self.missing)
        super().__init__(
            f"these packages define table models but ship no migration history: "
            f"{joined}. Run `terp migrate make <label>` to generate the first revision "
            f"and commit it; a deployed app builds its schema from packaged migrations, "
            f"never from dev-time schema auto-creation."
        )


class MigrationDriftError(MigrationError):
    """Committed migrations do not match the models: autogenerate still finds changes.

    Raised by :func:`terp.migrations.assert_migrations_match_models` (the reusable
    build-time drift check a consumer's test suite calls) so a model changed without a
    regenerated migration fails CI instead of silently shipping a schema that lags the
    code. The drifted packages are named so the fix is obvious.
    """

    def __init__(self, drifted: Sequence[str]) -> None:
        self.drifted = tuple(drifted)
        joined = ", ".join(self.drifted)
        super().__init__(
            f"committed migrations do not match the models for: {joined}. Run "
            f"`terp migrate make <label>` to regenerate the pending migration(s)."
        )


__all__ = [
    "MigrationDriftError",
    "MigrationError",
    "MissingMigrationsError",
    "PendingMigrationsError",
]
