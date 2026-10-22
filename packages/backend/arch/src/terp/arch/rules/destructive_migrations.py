"""The destructive-migration rule: a revision that is safe only against an empty database.

A deploy runs the new release's migrations while the previous release still serves,
and a rollback runs the previous release against the migrated schema. So a revision
has two audiences its author's scratch database never shows: the rows production
already holds, and the release that is still running. Five kinds of statement fail
one of them, and each is a finding here:

* a **drop** (a table, a column, ``TRUNCATE``, ``DELETE FROM``) destroys rows no later
  step can bring back;
* a **rename** (of a table or a column) breaks the running release, which still reads
  the old name;
* a **type change** can truncate or refuse existing values while the running release
  still writes the old type;
* a **NOT NULL tightening** of an existing column fails on the first row that holds
  ``NULL``, and the running release may still write one;
* a **constraint** added to an existing table (unique, check, foreign key, primary key,
  a unique index, a ``VALIDATE CONSTRAINT``) fails on the first row that breaks it,
  which an empty test database never holds.

Every finding names what to do instead, and it is the same shape each time: expand
(add the new column or table beside the old), backfill the rows with a job rather than a
statement in the revision, and contract — drop, tighten, constrain — in a later release.
The contract step is genuinely destructive, so it is the one that carries the standard
governed opt-out, ``# arch-allow-no-destructive-migrations: <reason>`` on or immediately
above the operation, counted by the escape-hatch budget.

Not reported is not the same as an expand step. The two exemptions below, a constraint
added ``NOT VALID``, a back-fill ``UPDATE`` and every other data write are steps no
existing row can break; none of them is thereby one the previous release is promised to
keep working after. Whether a revision can be rolled back without a restore is a separate
question, which this rule does not answer.

Two exemptions exist, and both are about rows that cannot be there yet. A table this
same ``upgrade()`` creates holds none, so tightening or constraining it cannot fail; and
a unique, foreign-key or unique-index constraint whose columns this ``upgrade()`` adds
nullable, with no server default, meets only ``NULL``\\ s, which those constraints accept.
The second is the shape autogenerate emits for a new reference column, and refusing it
would make the most common additive change a finding.
"""

from __future__ import annotations

import ast
import pathlib
import re
from collections.abc import Iterator

from terp.arch._ast import parse
from terp.arch.rules._support import ArchViolation, _rel
from terp.arch.rules.migrations import (
    _added_columns,
    _literal_name,
    _migration_files,
    _tables_created_in,
)

_DROP = "drop"
_RENAME = "rename"
_TYPE = "type"
_NOT_NULL = "not-null"
_CONSTRAINT = "constraint"

_MARKER = "'# arch-allow-no-destructive-migrations: <reason>'"

#: One message per kind of finding, each saying what to do instead.
_MESSAGES = {
    _DROP: (
        "migration drops data the running release may still read, and no later step can "
        "bring it back. Stop reading and writing it in one release, then remove it in a "
        f"later release: that contract step takes review and {_MARKER} (budgeted by the "
        "escape-hatch ratchet)"
    ),
    _RENAME: (
        "migration renames a table or column, and the release still running reads the "
        "old name. Expand instead: add the new name beside the old one and write both, "
        "backfill it with a job, move the readers, and drop the old name in a later "
        f"release, after review, with {_MARKER}"
    ),
    _TYPE: (
        "migration changes a column's type, which can truncate or refuse existing values "
        "while the running release still writes the old type. Add a column of the new "
        "type, backfill it with a job, move the readers, and drop the old column in a "
        f"later release; a pure widening that loses nothing takes review and {_MARKER}"
    ),
    _NOT_NULL: (
        "migration tightens an existing column to NOT NULL: it fails on the first row "
        "that holds NULL, and the running release may still write NULL. Backfill the "
        "NULLs with a job and make every writer set a value in this release, and tighten "
        f"it in a later release, after review, with {_MARKER}"
    ),
    _CONSTRAINT: (
        "migration adds a constraint every existing row must already satisfy, which an "
        "empty test database always does and a populated one may not. Clean or backfill "
        "the rows with a job in this release, and add the constraint in a later release, "
        f"after review, with {_MARKER}"
    ),
}

# Destructive SQL verbs a revision can smuggle through ``op.execute(...)``. Matched
# against string literals only (a statically reviewable statement); DROP TRIGGER /
# DROP FUNCTION / DROP INDEX are excluded — they destroy no row data — and so is
# ``DROP NOT NULL``, the relaxing direction ``alter_column(nullable=True)`` spells.
_DESTRUCTIVE_SQL_RE = re.compile(
    r"\b(DROP\s+TABLE|DROP\s+COLUMN|TRUNCATE(\s+TABLE)?|DELETE\s+FROM"
    r"|ALTER\s+TABLE\s+.+\bDROP\b(?!\s+NOT\s+NULL\b))\b",
    re.IGNORECASE | re.DOTALL,
)

# The rest are read one statement at a time, so a clause of one statement can never
# pair with the ``ALTER TABLE`` of another. A constraint rename is left alone: no
# query names a constraint, so the running release cannot be reading the old name.
_RENAME_SQL_RE = re.compile(
    r"\bALTER\s+TABLE\b.*?\bRENAME\b(?!\s+CONSTRAINT\b)|\bRENAME\s+TABLE\b",
    re.IGNORECASE | re.DOTALL,
)
_TYPE_SQL_RE = re.compile(
    r"\bALTER\s+TABLE\b.*?\bALTER\s+(?:COLUMN\s+)?(?!COLUMN\b)\S+\s+(?:SET\s+DATA\s+)?TYPE\b",
    re.IGNORECASE | re.DOTALL,
)
_NOT_NULL_SQL_RE = re.compile(
    r"\bALTER\s+TABLE\b.*?\bSET\s+NOT\s+NULL\b", re.IGNORECASE | re.DOTALL
)
_ADD_CONSTRAINT_SQL_RE = re.compile(
    r"\bALTER\s+TABLE\b.*?\bADD\s+(?:CONSTRAINT\s+(?:\"[^\"]*\"|\S+)\s+)?"
    r"(?P<kind>UNIQUE|PRIMARY\s+KEY|CHECK|FOREIGN\s+KEY|EXCLUDE)\b",
    re.IGNORECASE | re.DOTALL,
)
_ENFORCE_SQL_RE = re.compile(
    r"\bCREATE\s+UNIQUE\s+INDEX\b|\bVALIDATE\s+CONSTRAINT\b", re.IGNORECASE
)
#: ``NOT VALID`` skips the existing rows, which is the expand half of a check or a
#: foreign key; the ``VALIDATE CONSTRAINT`` that follows it is the contract half.
_NOT_VALID_RE = re.compile(r"\bNOT\s+VALID\b", re.IGNORECASE)
_NOT_VALID_KINDS = ("CHECK", "FOREIGN")

#: Calls whose arguments are a statement the database runs as written.
_EXECUTING = frozenset({"execute", "exec_driver_sql"})

#: For each constraint operation: the op-form position and keyword of its table, and
#: the op-form position and keyword of its columns (``None`` when it names none). On a
#: batch block the table comes from the block, so each position is one lower.
_CONSTRAINT_OPS: dict[str, tuple[int, str, int | None, str | None]] = {
    "create_unique_constraint": (1, "table_name", 2, "columns"),
    "create_primary_key": (1, "table_name", 2, "columns"),
    "create_foreign_key": (1, "source_table", 3, "local_cols"),
    "create_check_constraint": (1, "table_name", None, None),
    "create_exclude_constraint": (1, "table_name", None, None),
    "create_index": (1, "table_name", 2, "columns"),
}

#: The constraints a column that holds only ``NULL`` always satisfies. A primary key
#: refuses ``NULL`` and a check's condition names no columns this rule can read, so
#: neither is exempted by being on a new column.
_NULL_SATISFIES = frozenset({"create_unique_constraint", "create_foreign_key", "create_index"})

_PLACEHOLDER = " ? "


def _static_text(node: ast.expr) -> str | None:
    """The statement *node* spells, with each interpolated part read as a placeholder.

    A literal, an f-string and a ``+`` of strings are each one statement, so
    ``f"ALTER TABLE {name} RENAME TO entry"`` is read whole rather than as two halves
    that each look harmless. ``None`` when *node* holds no static text at all.
    """
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else None
    if isinstance(node, ast.JoinedStr):
        return "".join(
            part.value if isinstance(part, ast.Constant) else _PLACEHOLDER
            for part in node.values
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _static_text(node.left), _static_text(node.right)
        if left is None and right is None:
            return None
        return (left if left is not None else _PLACEHOLDER) + (
            right if right is not None else _PLACEHOLDER
        )
    return None


def _sql_texts(node: ast.AST) -> Iterator[str]:
    """Yield every statically known statement under *node* (``sa.text(...)`` included)."""
    text = _static_text(node) if isinstance(node, ast.expr) else None
    if text is not None:
        yield text
        return
    for child in ast.iter_child_nodes(node):
        yield from _sql_texts(child)


def _classify_statement(statement: str) -> str | None:
    """The kind of destructive step one SQL statement takes, if any."""
    if _RENAME_SQL_RE.search(statement):
        return _RENAME
    if _TYPE_SQL_RE.search(statement):
        return _TYPE
    if _NOT_NULL_SQL_RE.search(statement):
        return _NOT_NULL
    added = _ADD_CONSTRAINT_SQL_RE.search(statement)
    if added and not (
        added.group("kind").upper().startswith(_NOT_VALID_KINDS)
        and _NOT_VALID_RE.search(statement)
    ):
        return _CONSTRAINT
    if _ENFORCE_SQL_RE.search(statement):
        return _CONSTRAINT
    return None


def _classify_sql(call: ast.Call) -> str | None:
    """The kind of destructive step the statement an ``execute(...)`` runs takes."""
    for argument in [*call.args, *(keyword.value for keyword in call.keywords)]:
        for text in _sql_texts(argument):
            if _DESTRUCTIVE_SQL_RE.search(text):
                return _DROP
            for statement in text.split(";"):
                kind = _classify_statement(statement)
                if kind is not None:
                    return kind
    return None


def _is_false(node: ast.expr | None) -> bool:
    """True when *node* is the literal ``False``."""
    return isinstance(node, ast.Constant) and node.value is False


def _argument(
    call: ast.Call, position: int | None, keyword: str | None
) -> ast.expr | None:
    """The argument at *position*, or under *keyword*, of *call*."""
    if position is not None and 0 <= position < len(call.args):
        return call.args[position]
    for entry in call.keywords:
        if keyword is not None and entry.arg == keyword:
            return entry.value
    return None


def _literal_names(node: ast.expr | None) -> set[str] | None:
    """The column names a literal list or tuple of strings spells, else ``None``."""
    if not isinstance(node, ast.List | ast.Tuple) or not node.elts:
        return None
    names = {
        element.value
        for element in node.elts
        if isinstance(element, ast.Constant) and isinstance(element.value, str)
    }
    return names if len(names) == len(node.elts) else None


def _literal(node: ast.expr | None) -> str | None:
    """*node*'s value when it is a string literal."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


class _Upgrade:
    """What one ``upgrade()`` knows about the rows its operations can meet."""

    def __init__(self, function: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.created = _tables_created_in(function)
        #: Columns this upgrade adds nullable with no server default, per table: they
        #: hold only ``NULL`` on every existing row.
        self.null_only: dict[str | None, set[str]] = {}
        for _, column, table in _added_columns(function):
            keywords = {keyword.arg: keyword.value for keyword in column.keywords}
            name = _literal_name(column, keyword="name")
            if (
                name is None
                or _is_false(keywords.get("nullable"))
                or "server_default" in keywords
                or "primary_key" in keywords
            ):
                continue
            self.null_only.setdefault(table, set()).add(name)

    def classify(
        self, call: ast.Call, attr: str, batch_table: str | None, *, batch: bool
    ) -> str | None:
        """The kind of destructive step *call* takes, if any.

        *batch* says the call is made on a ``batch_alter_table`` block's handle, whose
        table is *batch_table* and whose operations therefore name no table themselves.
        Every other receiver is read in the op form, whatever it is called, so renaming
        the handle never unprotects the rule. An unresolvable table is one that may hold
        rows — the conservative direction, because the populated table is the case the
        rule exists for.
        """
        if attr in {"drop_table", "drop_column"}:
            return _DROP
        if attr == "rename_table":
            return _RENAME
        if attr == "alter_column":
            return self._classify_alter(call, batch_table, batch=batch)
        if attr in _CONSTRAINT_OPS:
            return self._classify_constraint(call, attr, batch_table, batch=batch)
        if attr in _EXECUTING:
            return _classify_sql(call)
        return None

    def _classify_alter(
        self, call: ast.Call, batch_table: str | None, *, batch: bool
    ) -> str | None:
        keywords = {keyword.arg: keyword.value for keyword in call.keywords}
        if "new_column_name" in keywords:
            return _RENAME
        if "type_" in keywords:
            return _TYPE
        # `existing_nullable=False` says the column already refuses NULL, so the call
        # restates the constraint rather than tightening it.
        if not _is_false(keywords.get("nullable")) or _is_false(
            keywords.get("existing_nullable")
        ):
            return None
        table = batch_table if batch else _literal(_argument(call, 0, "table_name"))
        return None if table in self.created else _NOT_NULL

    def _classify_constraint(
        self, call: ast.Call, attr: str, batch_table: str | None, *, batch: bool
    ) -> str | None:
        if attr == "create_index":
            unique = next((k.value for k in call.keywords if k.arg == "unique"), None)
            if not (isinstance(unique, ast.Constant) and unique.value is True):
                return None
        table_position, table_keyword, columns_position, columns_keyword = _CONSTRAINT_OPS[attr]
        shift = 1 if batch else 0
        if batch:
            table = batch_table
        else:
            table = _literal(_argument(call, table_position, table_keyword))
        if table is None:
            return _CONSTRAINT
        if table in self.created:
            return None
        if attr in _NULL_SATISFIES and columns_position is not None:
            columns = _literal_names(
                _argument(call, columns_position - shift, columns_keyword)
            )
            if columns is not None and columns <= self.null_only.get(table, set()):
                return None
        return _CONSTRAINT


def _calls(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[tuple[ast.Call, ast.Attribute, dict[str, str | None]]]:
    """Every method call in *function*, with the batch handles in scope where it is made.

    The handles map each ``as`` name of an enclosing ``batch_alter_table(...)`` block to
    that block's literal table (``None`` when the table is not a literal).
    """
    found: list[tuple[ast.Call, ast.Attribute, dict[str, str | None]]] = []

    def walk(node: ast.AST, handles: dict[str, str | None]) -> None:
        if isinstance(node, ast.With | ast.AsyncWith):
            inner = dict(handles)
            for item in node.items:
                walk(item.context_expr, handles)
                context = item.context_expr
                if (
                    isinstance(context, ast.Call)
                    and isinstance(context.func, ast.Attribute)
                    and context.func.attr == "batch_alter_table"
                    and isinstance(item.optional_vars, ast.Name)
                ):
                    inner[item.optional_vars.id] = _literal_name(
                        context, keyword="table_name"
                    )
            for statement in node.body:
                walk(statement, inner)
            return
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            found.append((node, node.func, handles))
        for child in ast.iter_child_nodes(node):
            walk(child, handles)

    walk(function, {})
    return found


def check_no_destructive_migrations(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """A revision may not take a step that is safe only against an empty database.

    In ``upgrade()``, on ``op``, a ``batch_alter_table`` block or any alias: a drop
    (``drop_table`` / ``drop_column``), a rename (``rename_table``,
    ``alter_column(new_column_name=...)``), a type change (``alter_column(type_=...)``),
    a NOT NULL tightening of an existing column (``alter_column(nullable=False)``), and
    a constraint added to an existing table (``create_unique_constraint`` /
    ``create_check_constraint`` / ``create_foreign_key`` / ``create_primary_key`` /
    ``create_exclude_constraint`` / ``create_index(unique=True)``). The same steps
    smuggled through ``execute(...)`` / ``exec_driver_sql(...)`` as a statically
    readable statement are caught too: ``DROP TABLE`` / ``DROP COLUMN`` /
    ``TRUNCATE`` / ``DELETE FROM`` / ``ALTER TABLE ... DROP``, ``ALTER TABLE ...
    RENAME`` / ``RENAME TABLE``, ``ALTER COLUMN ... TYPE``, ``SET NOT NULL``, ``ADD
    CONSTRAINT`` (a check or a foreign key ``NOT VALID`` excepted), ``CREATE UNIQUE
    INDEX`` and ``VALIDATE CONSTRAINT``.

    Each operation is one violation whose message says what to do instead — expand,
    backfill, contract in a later release — and the contract step, reviewed, carries
    ``# arch-allow-no-destructive-migrations: <reason>`` on (or immediately above) the
    operation, counted against the app's escape-hatch budget, so every accepted risk is
    explicit, reviewable, greppable, and ratcheted. See the module docstring for the two
    exemptions, both about rows that cannot exist yet.
    """
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    for path in _migration_files(root):
        rel = _rel(path, root)
        tree = parse(path)
        for function in ast.walk(tree):
            if not isinstance(function, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if function.name != "upgrade":
                continue
            upgrade = _Upgrade(function)
            for call, func, handles in _calls(function):
                receiver = func.value
                handle = receiver.id if isinstance(receiver, ast.Name) else None
                batch = handle in handles
                batch_table = handles.get(handle) if handle is not None else None
                kind = upgrade.classify(call, func.attr, batch_table, batch=batch)
                if kind is not None:
                    violations.append(
                        ArchViolation("no_destructive_migrations", rel, call.lineno, _MESSAGES[kind])
                    )
    return violations
