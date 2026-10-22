"""``terp secrets reseal`` — re-seal every value still under a retired key (ADR 0189).

A value sealed at rest opens under ``SECRET_KEY`` or under a
``SECRET_KEY_DECRYPT_FALLBACKS`` entry. After a rotation that list holds the old key,
and it may only come out of the environment once nothing in the database still needs
it. This command is how an operator gets there, and how they know they have:

* It walks every string column of every table the app maps, finds each value in the
  sealed ``enc:v1:`` format, and asks the sealing domains which key it opens under
  (:func:`terp.core.check_sealed_value`). The plaintext never reaches this module: a
  domain hands back the value already re-sealed under ``SECRET_KEY``.
* A value under a fallback is rewritten in place. A value already under ``SECRET_KEY``
  is left alone, so a second run writes nothing.
* ``--check`` only counts. The report says, per column, what opens under the current
  key, what was re-sealed, what still needs a fallback and what opens under no
  configured key at all; the exit status is 0 only when every sealed value opens under
  ``SECRET_KEY``.

Three properties make it safe to run against a live database:

* **One transaction per table.** A table that cannot be written (a trigger refusing
  the update, a lost connection) rolls back whole and is reported; the tables before
  and after it keep their re-seal.
* **Compare-and-swap per value.** The update matches the value it read, so a value
  the running app rewrote in the meantime — sealed under ``SECRET_KEY`` already — is
  never overwritten with the stale copy; it is counted as changed, and the next run
  judges it.
* **Nothing else moves.** A re-seal changes no value, only the key it is sealed under,
  so it writes no audit record and pins every column with an ``onupdate`` (the
  ``updated_at`` stamp) to itself; the ORM version counter is not touched either.

It refuses to run while a migration is pending: it writes rows, and it reads them
through the schema this code maps, which is the schema the migration is about to change.
"""

from __future__ import annotations

import functools
import json
import pathlib
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from terp.cli._appref import load_app, push_app_root
from terp.cli.schema import import_declared_models

if TYPE_CHECKING:
    from sqlalchemy import Column, Connection, Engine, Table

__all__ = ["ColumnTally", "ResealReport", "reseal_command", "survey"]

#: The format every sealing domain writes (``terp.core.secrets``). Matched with LIKE to
#: find the candidates; the domains, not the prefix, decide what a value is.
_SEALED_PREFIX = "enc:v1:"

#: Exit statuses. 1 is "something still needs attention"; 2 is "did not run".
_EXIT_CLEAN, _EXIT_REMAINS, _EXIT_REFUSED = 0, 1, 2


@dataclass
class ColumnTally:
    """One column's sealed values, by the key each opens under."""

    table: str
    column: str
    current: int = 0  # opens under SECRET_KEY
    resealed: int = 0  # rewritten under SECRET_KEY by this run
    fallback: int = 0  # still opens only under a SECRET_KEY_DECRYPT_FALLBACKS entry
    unreadable: int = 0  # opens under no configured key, in no registered domain
    changed: int = 0  # rewritten by someone else between this run's read and its write

    @property
    def found(self) -> int:
        return self.current + self.resealed + self.fallback + self.unreadable + self.changed


@dataclass
class ResealReport:
    """What one run found, wrote and could not reach."""

    wrote: bool
    columns: list[ColumnTally]
    failed: dict[str, str]  # table -> why it was rolled back

    def total(self, field: str) -> int:
        return sum(getattr(tally, field) for tally in self.columns)

    @property
    def clean(self) -> bool:
        """Every sealed value found opens under ``SECRET_KEY``, and every table was read."""
        return not self.failed and not any(
            self.total(field) for field in ("fallback", "unreadable", "changed")
        )


def _holds_text(column: Column[Any]) -> bool:
    """Whether *column* stores a string: through any type decorator, and never an enum.

    SQLModel maps ``str`` to ``AutoString``, a decorator over ``String`` rather than a
    subclass of it, so the type is unwrapped before it is judged. An enum is a ``String``
    to SQLAlchemy but a native type to PostgreSQL, where LIKE does not apply to it.
    """
    from sqlalchemy import Enum, String, TypeDecorator

    kind = column.type
    while isinstance(kind, TypeDecorator):
        kind = kind.impl
    return isinstance(kind, String) and not isinstance(kind, Enum)


def _string_columns(table: Table) -> list[Column[Any]]:
    """The columns that can hold a sealed value."""
    return [column for column in table.columns if _holds_text(column)]


def _settle(
    conn: Connection,
    table: Table,
    where: list[Any],
    column: Column[Any],
    stored: str,
    tally: ColumnTally,
    *,
    write: bool,
) -> None:
    """Count one sealed value, and with *write* re-seal it if it needs a fallback."""
    from sqlalchemy import update

    from terp.core import SealState, check_sealed_value

    check = check_sealed_value(stored)
    if check.state is SealState.CURRENT:
        tally.current += 1
        return
    if check.state is SealState.UNREADABLE:
        tally.unreadable += 1  # never rewritten: there is nothing true to re-seal
        return
    if not write:
        tally.fallback += 1
        return
    pinned = {other: other for other in table.columns if other.onupdate is not None}
    result = conn.execute(
        update(table)
        .where(*where, column == stored)
        .values({**pinned, column: check.resealed})
    )
    if result.rowcount == 1:
        tally.resealed += 1
    else:
        tally.changed += 1


def _survey_table(conn: Connection, table: Table, *, write: bool) -> list[ColumnTally]:
    """Every sealed value in *table*, counted and (with *write*) re-sealed."""
    from sqlalchemy import inspect, or_, select

    columns = _string_columns(table)
    primary = list(table.primary_key.columns)
    if not columns or not primary or not inspect(conn).has_table(table.name, schema=table.schema):
        return []
    tallies = {column.name: ColumnTally(table.name, column.name) for column in columns}
    rows = conn.execute(
        select(*primary, *columns).where(
            or_(*(column.like(f"{_SEALED_PREFIX}%") for column in columns))
        )
    ).all()
    for row in rows:
        where = [key == value for key, value in zip(primary, row[: len(primary)], strict=True)]
        for column, stored in zip(columns, row[len(primary) :], strict=True):
            if isinstance(stored, str) and stored.startswith(_SEALED_PREFIX):
                _settle(conn, table, where, column, stored, tallies[column.name], write=write)
    return [tally for tally in tallies.values() if tally.found]


def survey(engine: Engine, *, write: bool) -> ResealReport:
    """Walk every mapped table once, in one transaction per table."""
    from sqlalchemy.exc import SQLAlchemyError
    from sqlmodel import SQLModel

    report = ResealReport(wrote=write, columns=[], failed={})
    for table in SQLModel.metadata.sorted_tables:
        try:
            with engine.begin() as conn:
                tallies = _survey_table(conn, table, write=write)
        except SQLAlchemyError as exc:
            # The driver's own message, not SQLAlchemy's rendering of the statement:
            # that one carries the bound parameters, which here are sealed values.
            report.failed[table.name] = f"{type(exc).__name__}: {getattr(exc, 'orig', exc)}"
            continue
        report.columns.extend(tallies)
    return report


def _render(report: ResealReport) -> str:
    """The operator's report: one line per column that holds sealed values, then a verdict."""
    headings = ("column", "current", "re-sealed", "fallback", "unreadable", "changed")
    fields = ("current", "resealed", "fallback", "unreadable", "changed")
    lines = [(f"{tally.table}.{tally.column}", *(getattr(tally, f) for f in fields))
             for tally in report.columns]
    lines.append(("total", *(report.total(field) for field in fields)))
    width = max(len(str(line[0])) for line in [headings, *lines])
    out = ["Re-sealed under SECRET_KEY:" if report.wrote else "Checked; nothing was written:", ""]
    for line in [headings, *lines]:
        out.append(f"  {line[0]:<{width}}" + "".join(f"  {cell:>10}" for cell in line[1:]))
    out.append("")
    for table, reason in report.failed.items():
        out.append(f"Could not re-seal {table} ({reason}); nothing in it was written.")
    if report.total("fallback"):
        out.append(
            f"{report.total('fallback')} value(s) still open only under "
            "SECRET_KEY_DECRYPT_FALLBACKS. Run `terp secrets reseal` without --check, and "
            "keep the fallbacks until it reports none."
        )
    if report.total("unreadable"):
        out.append(
            f"{report.total('unreadable')} value(s) open under no configured key: sealed "
            "under a key no longer listed, or damaged. Add the key they were sealed under "
            "to SECRET_KEY_DECRYPT_FALLBACKS and run again, or enter them anew."
        )
    if report.total("changed"):
        out.append(
            f"{report.total('changed')} value(s) changed while being re-sealed; run again "
            "to judge them."
        )
    if report.clean:
        out.append(
            "Every sealed value opens under SECRET_KEY: SECRET_KEY_DECRYPT_FALLBACKS can "
            "come out of the environment. Keep each key it held for as long as a backup "
            "sealed under it may still be restored."
        )
    out.append(
        "SECRET_KEY_FALLBACKS only verifies signatures and is not judged here; drop it once "
        "the longest signature lifetime has passed (`terp guide secrets`)."
    )
    return "\n".join(out)


def reseal_command(
    *,
    app_ref: str = "app.main:app",
    app_root: str | pathlib.Path = ".",
    package: str = "app",
    check: bool = False,
    fmt: str = "text",
    migration_check: Callable[[Engine], None] | None = None,
) -> tuple[int, str]:
    """Run one re-seal (or, with *check*, one count) and return ``(exit status, report)``.

    *migration_check* defaults to the app's own boot guard over every declared history
    (``terp.migrations.assert_migrations_current``); injecting it keeps the refusal
    testable without a migrated database.
    """
    from terp.migrations.errors import MigrationError
    from terp.migrations.guard import assert_migrations_current

    from terp.cli._engine import cli_engine

    push_app_root(app_root)
    models_root = pathlib.Path(app_root).resolve() / package
    guard = migration_check or functools.partial(
        assert_migrations_current, app_root=models_root, package=package
    )
    try:
        load_app(app_ref)  # in production, the app's own boot guard runs here first
        engine = cli_engine()
        guard(engine)
    except MigrationError as exc:
        return _EXIT_REFUSED, (
            "terp secrets reseal refuses to run while a migration is pending or the "
            f"history does not match this code ({exc}). Run `terp migrate upgrade` first: "
            "a re-seal rewrites rows through the schema this code maps."
        )
    # Building the app imports the models of what it wires. A capability that is
    # installed and migrated but no longer wired still has its table and maybe its
    # sealed rows, so every declared package's models are imported too — which also
    # imports the capability, building its sealing domain so its values can be
    # re-sealed and not only found.
    import_declared_models(models_root, package=package)
    report = survey(engine, write=not check)
    status = _EXIT_CLEAN if report.clean else _EXIT_REMAINS
    if fmt == "json":
        payload = {
            "wrote": report.wrote,
            "clean": report.clean,
            "columns": [asdict(tally) for tally in report.columns],
            "failed": report.failed,
        }
        return status, json.dumps(payload, indent=2)
    return status, _render(report)
