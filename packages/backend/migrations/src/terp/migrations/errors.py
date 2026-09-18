"""Typed errors for the migration subsystem."""

from __future__ import annotations

from collections.abc import Mapping, Sequence


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


class DatabaseBehindForAutogenerateError(MigrationError):
    """``make`` was asked to autogenerate against a database that is not at head.

    Alembic refuses this for a good reason — it diffs the models against the *live*
    schema, so a database behind its own history produces a revision that re-creates
    what earlier revisions already create. Its own message ("Target database is not up
    to date.") arrives as a 25-line traceback that names neither the fix nor the far
    likelier cause: no ``DATABASE_URL``, so the command reached an empty database that
    has never had a migration applied to it. This is the first command a new module
    author runs, and ``terp migrate status`` \u2014 one word away in the same command group
    \u2014 already answers precisely; ``make`` should not be the one that answers in raw
    Alembic.

    It is also the *second* wall in a row: the in-memory refusal sends the author to a
    file database, which is then empty and therefore behind. Answering with a diagnosis
    would make them meet a third prompt. So the message leads with the two commands
    that satisfy both walls at once, against the database they are already pointing at.
    """

    def __init__(self, label: str, database_url: str) -> None:
        self.label = label
        super().__init__(
            f"cannot autogenerate a revision for {label!r}: the database at "
            f"{database_url!r} is not at head, so a diff against it would re-create "
            "tables that existing revisions already create.\n"
            "Bring it to head first \u2014 these two, in this order:\n"
            f'  DATABASE_URL="{database_url}" terp migrate upgrade\n'
            f'  DATABASE_URL="{database_url}" terp migrate make {label}\n'
            "(PowerShell: $env:DATABASE_URL='"
            f"{database_url}')\n"
            "`terp migrate status` shows which packages are behind if you want to look "
            "first.\n"
            "If that database should not be empty, check DATABASE_URL is pointing "
            "where you think it is \u2014 an unset one falls back to a local default.\n"
            "To author an empty revision and fill it in by hand, pass --no-autogenerate."
        )


class OrphanedRevisionsError(MigrationError):
    """The database has applied a revision the code no longer defines.

    Raised by :func:`terp.migrations.assert_no_orphaned_revisions` — the preflight
    ``terp migrate upgrade`` and the boot guard both run. It means an *already
    applied* migration was edited away or replaced by a fresh baseline: the schema in
    front of you was built by a history that no longer exists, so Alembic cannot work
    out what is left to do and every further upgrade fails. Autogenerate drift checks
    cannot see this — they build a scratch database from head, where the rewritten
    history is perfectly self-consistent — so the first symptom is otherwise an
    unbootable deployment.

    Both sanctioned recoveries are named, because which one is right depends on data:
    a development database can be recreated, a database holding real data must be
    re-baselined with ``terp migrate stamp`` once its schema is confirmed to match.
    """

    def __init__(self, orphaned: Mapping[str, Sequence[str]]) -> None:
        self.orphaned = {label: tuple(revs) for label, revs in orphaned.items()}
        joined = "; ".join(
            f"{label} is at {', '.join(revs)}" for label, revs in self.orphaned.items()
        )
        super().__init__(
            f"the database has applied migrations this code no longer defines: "
            f"{joined}. A migration that was already applied has been rewritten or "
            f"deleted. Recreate the database if it holds no data worth keeping, or — "
            f"if it does — confirm its schema matches the models and re-baseline it "
            f"with `terp migrate stamp <label> <revision>`. Never resolve this by "
            f"editing history further."
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


class MigrationReversibilityError(MigrationError):
    """A downgrade did not put the schema back the way it found it.

    Raised by :func:`terp.migrations.assert_migrations_reverse_cleanly`. Every Terp
    app's rollback plan is ``terp migrate downgrade``, and until this existed the only
    thing checked about that plan was that the ``downgrade()`` body was not an empty
    stub — a source-level check that cannot see a downgrade which dies on its first
    statement, and cannot see one that runs green and comes back with a different
    schema.

    The second is the quiet one: a downgrade that leaves a table, index or trigger
    behind runs green, and the next upgrade either collides with the residue or reflects
    it into a rebuilt table — so the schema you roll forward into is not the one the
    version you rolled back to was tested against.

    The differences are named as ``<object>: before | after`` so the reader can see
    which object changed and in which direction, rather than being told only that
    something did.
    """

    def __init__(self, differences: Sequence[str]) -> None:
        self.differences = tuple(differences)
        listed = "".join(f"\n  - {difference}" for difference in self.differences)
        super().__init__(
            f"the migration history does not reverse cleanly ({len(self.differences)} "
            f"difference(s) after downgrade to base and upgrade again):{listed}\n"
            "A downgrade that does not restore what it found is a rollback plan that "
            "changes the schema under the version you are rolling back to."
        )


class MigrationResidueError(MigrationError):
    """A downgrade to base left schema objects behind.

    Raised by :func:`terp.migrations.assert_migrations_reverse_cleanly`. This is the
    failure the catalogued ``alembic_downgrades_not_empty`` rule most looks like it
    covers and cannot: a ``downgrade()`` with statements in it that simply do not undo
    everything the ``upgrade()`` did. An index, a table, a trigger or a view the reverse
    direction forgot.

    It is quiet by construction. Nothing errors, and a down-and-up cycle usually
    converges back to the same schema — so comparing the two ends of the cycle does not
    see it either. What sees it is looking at the middle: after a full downgrade the
    database should hold nothing but the (empty) ``alembic_version_<label>`` bookkeeping
    tables, and anything else is something a rollback would leave on a production
    database for the next deploy to collide with.
    """

    def __init__(self, leftovers: Sequence[str]) -> None:
        self.leftovers = tuple(leftovers)
        listed = "".join(f"\n  - {leftover}" for leftover in self.leftovers)
        super().__init__(
            f"downgrade to base left {len(self.leftovers)} object(s) behind:{listed}\n"
            "After a full downgrade the database should hold nothing but the empty "
            "alembic_version_<label> tables. Each object above is something a rollback "
            "would leave on a production database for the next deploy to meet."
        )


class MigrationHistoryNotEmptiedError(MigrationError):
    """A downgrade to base left a package's history marked as applied.

    Raised by :func:`terp.migrations.assert_migrations_reverse_cleanly`. Each package
    keeps its own ``alembic_version_<label>`` bookkeeping table, and a downgrade to
    base must empty every one of them. A history still holding a revision after a full
    downgrade means that package never went down, so the next upgrade skips it and the
    tables it owns are whatever the failed downgrade left behind.
    """

    def __init__(self, labels: Sequence[str]) -> None:
        self.labels = tuple(labels)
        joined = ", ".join(self.labels)
        super().__init__(
            f"downgrade to base left a revision applied for: {joined}. Every package's "
            "alembic_version_<label> table must be empty after a full downgrade; one "
            "that is not means that history never went down."
        )


__all__ = [
    "MigrationDriftError",
    "MigrationError",
    "MigrationHistoryNotEmptiedError",
    "MigrationResidueError",
    "MigrationReversibilityError",
    "MissingMigrationsError",
    "OrphanedRevisionsError",
    "PendingMigrationsError",
]
