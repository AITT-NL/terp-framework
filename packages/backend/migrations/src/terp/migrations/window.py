"""The schema window a release accepts (ADR 0185 decisions 2 and 3).

The migration run records every revision it applies in one table outside every package
history, ``terp_migration_window`` (``public`` on PostgreSQL, under either layout): the
package label, the revision, its parent, ``expand`` or ``contract``, ``applied_by`` (the
SHA-256 of the canonical JSON of the run's own code heads per package), ``applied_terp``
(the run's lockstep Terp version), ``seq`` (rising with every insert) and the time. A row
is written in the same transaction as the version-table update for its revision, so the
record cannot drift from the schema it describes, and a backup carries it.

The boot guard, the ``migrate`` preflight and ``terp migrate check`` read it alike
(:func:`judge_window`). A package whose applied revision the code does not define is
walked back through the record to the code's head; and every row is held to two rules:

* (a) every row the newest run wrote for a revision this code does not define is
  ``expand`` and carries this code's Terp version;
* the *horizon* is the newest row a run of this code itself wrote (its ``applied_by`` is
  this code's own heads digest); every row above it for a revision this code does not
  define is the newest run's.

So the window is one run deep in every package and the guard enforces the depth itself:
no option, label or deploy tool tells it which release was running.

A package the app removed is retired: it lists the label in a literal
``RETIRED_MIGRATIONS`` tuple in ``<app root>/modules/__init__.py``, read with ``ast``
and never imported, and its rows are ignored. A list that cannot be read is never read
as empty.
"""

from __future__ import annotations

import ast
import datetime
import hashlib
import importlib.metadata
import json
import logging
import pathlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    func,
    inspect,
    select,
)
from sqlalchemy.exc import SQLAlchemyError

from terp.migrations.errors import OrphanedRevisionsError, RetiredMigrationsError

#: The record's table name. It lives in ``public`` on PostgreSQL under either layout,
#: beside the version tables, so a layout-unaware read finds it.
RECORD_TABLE = "terp_migration_window"

#: Capability histories Terp itself retired: their labels, ignored like an app's own.
TERP_RETIRED_MIGRATIONS: tuple[str, ...] = ()

#: The name the app's retired list is read under, in ``<app root>/modules/__init__.py``.
RETIRED_NAME = "RETIRED_MIGRATIONS"

EXPAND = "expand"
CONTRACT = "contract"

_logger = logging.getLogger("terp.migrations")


def record_schema(dialect_name: str) -> str | None:
    """``public`` on PostgreSQL; SQLite has no schemas to qualify by."""
    return "public" if dialect_name == "postgresql" else None


def record_table(dialect_name: str) -> Table:
    """The record's shape. It only ever gains columns."""
    return Table(
        RECORD_TABLE,
        MetaData(),
        Column("label", String(255), nullable=False),
        Column("revision", String(255), nullable=False),
        Column("parent", String(255), nullable=True),
        Column("kind", String(16), nullable=False),
        Column("applied_by", String(64), nullable=False),
        Column("applied_terp", String(64), nullable=False),
        Column("seq", BigInteger, nullable=False),
        Column("applied_at", DateTime(timezone=True), nullable=False),
        PrimaryKeyConstraint("label", "revision", name=f"{RECORD_TABLE}_pkey"),
        schema=record_schema(dialect_name),
    )


def ensure_record_table(connection: Any) -> Table:
    """Create the record when it is missing, and only then: a rollback writes nothing."""
    table = record_table(connection.dialect.name)
    if not inspect(connection).has_table(RECORD_TABLE, schema=table.schema):
        table.create(connection)
    return table


def terp_version() -> str:
    """The run's lockstep Terp version (ADR 0063), as ``terp-migrations`` reports it."""
    return importlib.metadata.version("terp-migrations")


def heads_digest(heads: Mapping[str, Iterable[str]]) -> str:
    """The SHA-256 of the canonical JSON of *heads* (``{label: [head, ...]}``)."""
    canonical = json.dumps(
        {label: sorted(revisions) for label, revisions in heads.items()},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def write_record_row(
    connection: Any,
    *,
    label: str,
    revision: str,
    parent: str | None,
    kind: str,
    applied_by: str,
    applied_terp: str,
) -> None:
    """Record one applied revision; a revision applied again replaces its row."""
    table = ensure_record_table(connection)
    connection.execute(
        table.delete().where(table.c.label == label, table.c.revision == revision)
    )
    seq = connection.execute(select(func.coalesce(func.max(table.c.seq), 0) + 1)).scalar_one()
    connection.execute(
        table.insert().values(
            label=label,
            revision=revision,
            parent=parent,
            kind=kind,
            applied_by=applied_by,
            applied_terp=applied_terp,
            seq=seq,
            applied_at=datetime.datetime.now(datetime.UTC),
        )
    )


def delete_record_rows(
    connection: Any,
    label: str,
    *,
    keep: Iterable[str] | None = None,
    revisions: Iterable[str] | None = None,
) -> None:
    """Delete *label*'s rows: those for *revisions*, or every one not in *keep*."""
    table = record_table(connection.dialect.name)
    if not inspect(connection).has_table(RECORD_TABLE, schema=table.schema):
        return
    statement = table.delete().where(table.c.label == label)
    if revisions is not None:
        statement = statement.where(table.c.revision.in_(list(revisions)))
    if keep is not None:
        kept = list(keep)
        if kept:
            statement = statement.where(table.c.revision.not_in(kept))
    connection.execute(statement)


@dataclass(frozen=True)
class RecordRow:
    """One row of the record."""

    label: str
    revision: str
    parent: str | None
    kind: str
    applied_by: str
    applied_terp: str
    seq: int


def read_record(connection: Any) -> list[RecordRow] | None:
    """Every row, or ``None`` when the record is missing or its shape cannot be read.

    ``None`` is not an error: a database no run on this decision migrated has no record,
    and one whose record a newer release reshaped is treated as outside the window
    rather than failed on.
    """
    table = record_table(connection.dialect.name)
    try:
        inspector = inspect(connection)
        if not inspector.has_table(RECORD_TABLE, schema=table.schema):
            return None
        present = {column["name"] for column in inspector.get_columns(RECORD_TABLE, schema=table.schema)}
        if not {column.name for column in table.columns} <= present:
            return None
        result = connection.execute(
            select(
                table.c.label,
                table.c.revision,
                table.c.parent,
                table.c.kind,
                table.c.applied_by,
                table.c.applied_terp,
                table.c.seq,
            )
        ).all()
    except SQLAlchemyError:
        # Unreadable (a privilege, a type): outside the window, and the connection is put
        # back so the rest of the judgment can still read the version tables.
        connection.rollback()
        return None
    return [
        RecordRow(str(r[0]), str(r[1]), None if r[2] is None else str(r[2]), str(r[3]),
                  str(r[4]), str(r[5]), int(r[6]))
        for r in result
    ]


def read_retired_migrations(app_root: str | pathlib.Path | None) -> tuple[str, ...]:
    """The labels the app retired, plus Terp's own, read with ``ast`` and never imported.

    The list lives in ``<app root>/modules/__init__.py`` because every image carries the
    app root (``pyproject.toml`` would be simpler to edit, but the runtime image does not
    carry it). It must be one module-level assignment of a literal tuple of strings;
    anything else refuses, because a list read as empty quietly un-retires every package.
    """
    retired = list(TERP_RETIRED_MIGRATIONS)
    if app_root is None:
        return tuple(retired)
    path = pathlib.Path(app_root) / "modules" / "__init__.py"
    if not path.is_file():
        return tuple(retired)
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, ValueError) as exc:
        raise RetiredMigrationsError(
            f"{path} cannot be parsed, so {RETIRED_NAME} cannot be read; the window "
            "(ADR 0185) is never judged with an unread list"
        ) from exc
    found: list[ast.AST] = []
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign | ast.AugAssign):
            targets = [node.target]
        if any(isinstance(target, ast.Name) and target.id == RETIRED_NAME for target in targets):
            found.append(node)
    if not found:
        return tuple(retired)
    node = found[0]
    value = getattr(node, "value", None)
    if (
        len(found) > 1
        or node not in tree.body
        or isinstance(node, ast.AugAssign)
        or not isinstance(value, ast.Tuple)
        or not all(
            isinstance(item, ast.Constant) and isinstance(item.value, str) for item in value.elts
        )
    ):
        raise RetiredMigrationsError(
            f"{RETIRED_NAME} in {path} must be one module-level assignment of a literal "
            f"tuple of strings, such as {RETIRED_NAME} = (\"invoices\",); it is read "
            "without importing the app, and a list that cannot be read is never taken as "
            "empty"
        )
    retired.extend(str(item.value) for item in value.elts)  # type: ignore[union-attr]
    return tuple(dict.fromkeys(retired))


# --------------------------------------------------------------------------- #
# Judging the window                                                           #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CodeHistory:
    """One package history as the code defines it."""

    label: str
    heads: tuple[str, ...]
    known: frozenset[str]
    version_table: str


@dataclass(frozen=True)
class Window:
    """What the judged database holds relative to the code."""

    #: Labels at a revision the code does not define, inside the window, with the
    #: revisions the code runs behind (newest first).
    ahead: dict[str, tuple[str, ...]] = field(default_factory=dict)
    #: Labels the code does not define whose rows the window admits.
    foreign: dict[str, tuple[str, ...]] = field(default_factory=dict)
    #: Labels whose applied revisions the code defines (its head, an ancestor, or none).
    current: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def warn(self) -> None:
        """Log the one warning a guard that admits a window gives at boot."""
        behind = {**self.ahead, **self.foreign}
        if not behind:
            return
        described = "; ".join(
            f"{label} ({', '.join(revisions)})" for label, revisions in sorted(behind.items())
        )
        _logger.warning(
            "the database is ahead of this code inside its schema window (ADR 0185): it "
            "runs behind %s",
            described,
        )


def code_history(script: ScriptDirectory, label: str, version_table: str) -> CodeHistory:
    known = frozenset(rev.revision for rev in script.walk_revisions())
    return CodeHistory(label, tuple(script.get_heads()), known, version_table)


def _applied(connection: Any, history: CodeHistory) -> tuple[str, ...]:
    context = MigrationContext.configure(
        connection, opts={"version_table": history.version_table}
    )
    return tuple(context.get_current_heads())


def _walk(
    revision: str, history: CodeHistory, parents: Mapping[str, str | None]
) -> tuple[tuple[str, ...], str | None]:
    """Walk *revision* back through the record to the code. ``(crossed, refusal)``."""
    crossed: list[str] = []
    current: str | None = revision
    while current is not None and current not in history.known:
        if current in crossed or current not in parents:
            return tuple(crossed), (
                f"{current} is neither in this code's history nor in the migration record "
                "(a history rewritten after it was applied, a record that was lost, or a "
                "release applied from an offline script)"
            )
        crossed.append(current)
        current = parents[current]
    if current is None or current not in history.heads:
        return tuple(crossed), (
            "the database holds expand revisions this release's history dropped "
            f"({', '.join(crossed)}): every release after a rollback keeps the revision "
            "files, model fields and tables of the release it rolled back from, so cut the "
            "release from that one"
        )
    return tuple(crossed), None


def _row_refusal(
    row: RecordRow, *, newest: str | None, horizon: int, own_terp: str
) -> str | None:
    """Why rule (a) or the horizon refuses *row*, for a revision the code does not define."""
    if row.applied_by == newest:
        if row.kind != EXPAND:
            return (
                f"the newest migration run applied {row.revision}, a contract revision this "
                "code does not define"
            )
        if row.applied_terp != own_terp:
            return (
                f"the newest migration run applied {row.revision} on Terp {row.applied_terp} "
                f"and this code runs {own_terp}; a window never crosses a Terp update"
            )
        return None
    if row.seq > horizon:
        return (
            f"{row.revision} was applied by a migration run before the newest one and after "
            "this code last migrated: the database is more than one migration run ahead"
        )
    return None


def judge_window(
    connection: Any,
    histories: Sequence[CodeHistory],
    own_digest: str,
    *,
    retired: Sequence[str],
    own_terp: str | None = None,
) -> Window:
    """Judge the database behind *connection* against the code's *histories*.

    Raises :class:`OrphanedRevisionsError` naming each package the window does not admit,
    with the reason; returns the :class:`Window` otherwise.
    """
    own_terp = own_terp if own_terp is not None else terp_version()
    retired_set = set(retired)
    rows = [row for row in read_record(connection) or [] if row.label not in retired_set]
    by_label = {history.label: history for history in histories}
    applied = {history.label: _applied(connection, history) for history in histories}
    newest = max(rows, key=lambda row: row.seq).applied_by if rows else None
    horizon = max((row.seq for row in rows if row.applied_by == own_digest), default=0)
    orphaned: dict[str, tuple[str, ...]] = {}
    reasons: dict[str, str] = {}
    window = Window()

    # The two rules, over every row of every package the code does not retire.
    for row in sorted(rows, key=lambda row: row.seq):
        history = by_label.get(row.label)
        if (history is not None and row.revision in history.known) or row.label in reasons:
            continue
        refusal = _row_refusal(row, newest=newest, horizon=horizon, own_terp=own_terp)
        if refusal is None:
            if history is None and row.seq > horizon:
                window.foreign[row.label] = (row.revision, *window.foreign.get(row.label, ()))
            continue
        if history is None:
            orphaned[row.label] = (row.revision,)
            reasons[row.label] = (
                f"the database holds revisions of {row.label!r}, which this code does not "
                "define: if this release removed it, retire it in this release; if a newer "
                f"release installed it, this rollback is restore-based ({refusal})"
            )
        else:
            orphaned[row.label] = applied[row.label] or (row.revision,)
            reasons[row.label] = refusal

    # The walk, for each package the code defines whose applied revision it does not.
    for history in histories:
        unknown = [revision for revision in applied[history.label] if revision not in history.known]
        if not unknown:
            window.current[history.label] = applied[history.label]
            continue
        parents = {row.revision: row.parent for row in rows if row.label == history.label}
        for revision in unknown:
            crossed, refusal = _walk(revision, history, parents)
            if refusal is not None:
                orphaned[history.label] = tuple(unknown)
                reasons.setdefault(history.label, refusal)
                break
            window.ahead[history.label] = crossed
    if orphaned:
        raise OrphanedRevisionsError(orphaned, reasons)
    return window


def histories_of(
    trees: Sequence[Any], database_url: str, config_for: Any
) -> list[CodeHistory]:
    """The :class:`CodeHistory` of each runnable tree, read from its revision files."""
    return [
        code_history(
            ScriptDirectory.from_config(config_for(tree, database_url)),
            tree.label,
            tree.version_table,
        )
        for tree in trees
    ]


__all__ = [
    "CONTRACT",
    "EXPAND",
    "RECORD_TABLE",
    "RETIRED_NAME",
    "TERP_RETIRED_MIGRATIONS",
    "CodeHistory",
    "RecordRow",
    "Window",
    "code_history",
    "delete_record_rows",
    "ensure_record_table",
    "heads_digest",
    "histories_of",
    "judge_window",
    "read_record",
    "read_retired_migrations",
    "record_table",
    "terp_version",
    "write_record_row",
]
