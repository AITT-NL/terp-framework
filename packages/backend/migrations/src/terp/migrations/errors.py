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


__all__ = ["MigrationDriftError", "MigrationError", "PendingMigrationsError"]
