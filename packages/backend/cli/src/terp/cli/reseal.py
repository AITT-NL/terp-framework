"""``terp secrets reseal`` — re-seal every value still under a retired key (ADR 0189).

A value sealed at rest opens under ``SECRET_KEY`` or under a
``SECRET_KEY_DECRYPT_FALLBACKS`` entry. After a rotation that list holds the old key,
and it may only come out of the environment once nothing in the database still needs
it. This command is how an operator gets there, and how they know they have:

* It walks every string column of every table the app maps, finds each value in the
  sealed ``enc:v1:`` format, and asks the sealing domains which key it opens under
  (:func:`terp.core.check_sealed_value`). The plaintext never reaches this module: a
  domain hands back the value already re-sealed under ``SECRET_KEY``.
* It walks every JSON column too, and judges each string nested in a document, at any
  depth, the same way (ADR 0199). A queued mail is one: its message is a sealed value
  inside an ``outbox_message.payload``, and a check that saw string columns only would
  call a database clean while that mail still needed the fallback to be sent.
* A value under a fallback is rewritten in place. A value already under ``SECRET_KEY``
  is left alone, so a second run writes nothing.
* A table it can read but not rewrite is still read, and named. A mapped table with no
  primary key cannot be updated one row at a time, and a table in the database that the
  app does not map has no model to write through. Their sealed values are counted, so a
  value in one that still needs a fallback keeps the verdict from being clean, and the
  report names each such table and why nothing in it was re-sealed.
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
  judges it. A document is matched on its text form as it was read, because
  PostgreSQL's ``json`` has no equality: a change to anything in it since the read
  loses the swap, and every value that would have been re-sealed in it is counted as
  changed.
* **Nothing else moves.** A re-seal changes no value, only the key it is sealed under,
  so it writes no audit record and pins every column with an ``onupdate`` (the
  ``updated_at`` stamp) to itself; the ORM version counter is not touched either. A
  document is written back through its column's own type with only its sealed values
  replaced, every other key and value as it was read.

It refuses to run while a migration is pending: it writes rows, and it reads them
through the schema this code maps, which is the schema the migration is about to change.
"""

from __future__ import annotations

import functools
import json
import pathlib
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

from terp.cli._appref import load_app, push_app_root
from terp.cli.schema import import_declared_models

if TYPE_CHECKING:
    from sqlalchemy import Column, Connection, Engine, MetaData, Table

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
    skipped: dict[str, str] = field(default_factory=dict)  # table -> why nothing was re-sealed

    def total(self, name: str) -> int:
        return sum(getattr(tally, name) for tally in self.columns)

    @property
    def clean(self) -> bool:
        """Every sealed value found opens under ``SECRET_KEY``, and every table was read.

        A skipped table was read, so its values are in the totals: one that still needs a
        fallback keeps the report from being clean, and one that opens under ``SECRET_KEY``
        needs nothing.
        """
        return not self.failed and not any(
            self.total(name) for name in ("fallback", "unreadable", "changed")
        )


def _kind(column: Column[Any]) -> Any:
    """*column*'s type through any type decorator.

    SQLModel maps ``str`` to ``AutoString``, a decorator over ``String`` rather than a
    subclass of it, so the type is unwrapped before it is judged.
    """
    from sqlalchemy import TypeDecorator

    kind = column.type
    while isinstance(kind, TypeDecorator):
        kind = kind.impl
    return kind


def _holds_text(column: Column[Any]) -> bool:
    """Whether *column* stores a string, and never an enum.

    An enum is a ``String`` to SQLAlchemy but a native type to PostgreSQL, where LIKE does
    not apply to it.
    """
    from sqlalchemy import Enum, String

    kind = _kind(column)
    return isinstance(kind, String) and not isinstance(kind, Enum)


def _holds_json(column: Column[Any]) -> bool:
    """Whether *column* stores a JSON document (``JSONB`` and a reflected ``JSON`` included)."""
    from sqlalchemy import JSON

    return isinstance(_kind(column), JSON)


def _judge(stored: str, tally: ColumnTally, *, write: bool) -> str | None:
    """Count one sealed value; return its re-sealing when it needs a fallback and *write*."""
    from terp.core import SealState, check_sealed_value

    check = check_sealed_value(stored)
    if check.state is SealState.CURRENT:
        tally.current += 1
    elif check.state is SealState.UNREADABLE:
        tally.unreadable += 1  # never rewritten: there is nothing true to re-seal
    elif not write:
        tally.fallback += 1
    else:
        return check.resealed
    return None


def _swap(
    conn: Connection, table: Table, where: list[Any], read: Any, column: Column[Any], value: Any
) -> bool:
    """Write *value* to *column* of the row *where* names, if *read* still matches it."""
    from sqlalchemy import update

    pinned = {other: other for other in table.columns if other.onupdate is not None}
    result = conn.execute(update(table).where(*where, read).values({**pinned, column: value}))
    return result.rowcount == 1


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
    resealed = _judge(stored, tally, write=write)
    if resealed is None:
        return
    if _swap(conn, table, where, column == stored, column, resealed):
        tally.resealed += 1
    else:
        tally.changed += 1


def _resealed(value: Any, settle: Callable[[str], str]) -> Any:
    """*value* with every string in the sealed format, a key or a value at any depth, settled."""
    if isinstance(value, str):
        return settle(value) if value.startswith(_SEALED_PREFIX) else value
    if isinstance(value, list):
        return [_resealed(item, settle) for item in value]
    if isinstance(value, dict):
        return {_resealed(key, settle): _resealed(item, settle) for key, item in value.items()}
    return value


def _settle_document(
    conn: Connection,
    table: Table,
    where: list[Any],
    column: Column[Any],
    text: str,
    tally: ColumnTally,
    *,
    write: bool,
) -> None:
    """Count every sealed value in one JSON document; with *write*, re-seal those under a fallback.

    The document is read as text, so the swap can match the text it read. A document that
    does not parse holds the sealed format somewhere no walk can reach, so it is counted as
    one value no key opens, and the report is not clean while it is there.
    """
    from sqlalchemy import Text, cast

    try:
        document = json.loads(text)
    except ValueError:
        tally.unreadable += 1
        return
    pending: list[str] = []

    def settle(stored: str) -> str:
        resealed = _judge(stored, tally, write=write)
        if resealed is None:
            return stored
        pending.append(resealed)
        return resealed

    document = _resealed(document, settle)
    if not pending:
        return
    if _swap(conn, table, where, cast(column, Text) == text, column, document):
        tally.resealed += len(pending)
    else:
        tally.changed += len(pending)


def _survey_table(conn: Connection, table: Table, *, write: bool) -> list[ColumnTally]:
    """Every sealed value in *table*, counted and (with *write*) re-sealed.

    A table with no primary key is counted and never written: without a key, an update
    that matches a row matches every row holding the same value. A JSON column is read as
    its text form, and only a row whose text holds the sealed format somewhere is walked.
    """
    from sqlalchemy import Text, cast, inspect, or_, select

    columns = [column for column in table.columns if _holds_text(column)]
    documents = [column for column in table.columns if _holds_json(column)]
    primary = list(table.primary_key.columns)
    write = write and bool(primary)
    if not (columns or documents) or not inspect(conn).has_table(table.name, schema=table.schema):
        return []
    tallies = {column.name: ColumnTally(table.name, column.name) for column in [*columns, *documents]}
    texts = [cast(document, Text) for document in documents]
    rows = conn.execute(
        select(*primary, *columns, *texts).where(
            or_(
                *(column.like(f"{_SEALED_PREFIX}%") for column in columns),
                *(text.like(f'%"{_SEALED_PREFIX}%') for text in texts),
            )
        )
    ).all()
    for row in rows:
        where = [key == value for key, value in zip(primary, row[: len(primary)], strict=True)]
        values = row[len(primary) :]
        for column, stored in zip(columns, values[: len(columns)], strict=True):
            if isinstance(stored, str) and stored.startswith(_SEALED_PREFIX):
                _settle(conn, table, where, column, stored, tallies[column.name], write=write)
        for document, text in zip(documents, values[len(columns) :], strict=True):
            if text is not None and f'"{_SEALED_PREFIX}' in text:
                tally = tallies[document.name]
                _settle_document(conn, table, where, document, text, tally, write=write)
    return [tally for tally in tallies.values() if tally.found]


#: Why a table that holds sealed values had none of them re-sealed.
_NO_PRIMARY_KEY = "it has no primary key, so no value in it can be rewritten one row at a time"
_UNMAPPED = "the app does not map it, so there is no model to write it through"
#: Where the database's own tables are listed, when the app maps none of its tables there.
_OTHER_TABLES = "the database's tables the app does not map"


def _failure(exc: Exception) -> str:
    # The driver's own message, not SQLAlchemy's rendering of the statement: that one
    # carries the bound parameters, which here are sealed values.
    return f"{type(exc).__name__}: {getattr(exc, 'orig', exc)}"


def _unmapped_tables(conn: Connection, metadata: MetaData) -> list[Table]:
    """The tables the database holds, in the schemas the app maps into, that it does not map.

    Each is reflected from the database, so its string columns can be read.
    """
    from sqlalchemy import MetaData, Table, inspect

    mapped = {(table.schema, table.name) for table in metadata.sorted_tables}
    schemas = sorted({None, *(schema for schema, _ in mapped)}, key=lambda schema: schema or "")
    inspector = inspect(conn)
    reflected = MetaData()
    return [
        Table(name, reflected, schema=schema, autoload_with=conn)
        for schema in schemas
        for name in inspector.get_table_names(schema=schema)
        if (schema, name) not in mapped
    ]


def survey(engine: Engine, *, write: bool, metadata: MetaData | None = None) -> ResealReport:
    """Walk every mapped table once, in one transaction per table, then read the rest.

    *metadata* is the app's mapping, ``SQLModel.metadata`` unless a caller names another.
    A table the database holds and the app does not map is read too, never written.
    """
    from sqlalchemy.exc import SQLAlchemyError
    from sqlmodel import SQLModel

    mapping = metadata if metadata is not None else SQLModel.metadata
    report = ResealReport(wrote=write, columns=[], failed={})

    def read(table: Table, *, writable: bool, skipped: str | None) -> None:
        try:
            with engine.begin() as conn:
                tallies = _survey_table(conn, table, write=write and writable)
        except SQLAlchemyError as exc:
            report.failed[table.name] = _failure(exc)
            return
        report.columns.extend(tallies)
        if tallies and skipped is not None:
            report.skipped[table.name] = skipped

    for table in mapping.sorted_tables:
        keyless = not table.primary_key.columns
        read(table, writable=True, skipped=_NO_PRIMARY_KEY if keyless else None)
    try:
        with engine.connect() as conn:
            unmapped = _unmapped_tables(conn, mapping)
    except SQLAlchemyError as exc:
        report.failed[_OTHER_TABLES] = _failure(exc)
        return report
    for table in unmapped:
        read(table, writable=False, skipped=_UNMAPPED)
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
    for table, reason in report.skipped.items():
        out.append(
            f"Read {table} but re-sealed nothing in it: {reason}. Its values are counted "
            "above; re-seal any that need a fallback through the code that owns it."
        )
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
            "skipped": report.skipped,
        }
        return status, json.dumps(payload, indent=2)
    return status, _render(report)
