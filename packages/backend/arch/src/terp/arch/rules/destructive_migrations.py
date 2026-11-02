"""The destructive-migration rule: a revision that is safe only against an empty database.

A deploy runs the new release's migrations while the previous release still serves,
and a rollback runs the previous release against the migrated schema. So a revision
has two audiences its author's scratch database never shows: the rows production
already holds, and the release that is still running. Five kinds of statement fail
one of them, and each is a finding here:

* a **drop** (a table, a column, a schema, ``TRUNCATE``, ``DELETE FROM``) destroys rows
  no later step can bring back;
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

What the migration runs is what is read, not only what ``upgrade()`` spells itself: a
function of the same revision that ``upgrade()`` calls by name is read as part of it, and
so is each one that calls, transitively; an operation imported by name (``from alembic.op
import drop_column``) or named by a literal ``getattr(op, "drop_table")`` is that
operation; and ``upgrade = _up`` makes ``_up`` the upgrade. A statement is read one at a
time, so ``"DROP TABLE a; ALTER TABLE b RENAME TO c"`` is two findings. What has no static
form (a statement held in a variable, an operation whose name is computed) is not read.

What the rule finds in one revision is also a value, :func:`destructive_operations`, for
a reader that lists a release's destructive steps rather than gating them: each one,
excused by its marker or not, with its kind, its line, its place in the revision and a
line of text that names it. The rule reports exactly that list's five kinds, so the gate
and such a reader cannot disagree about what is destructive. The list also holds what the
rule cannot read, as a sixth kind, ``opaque``: a statement with no static text and a call
the reading cannot follow. The rule reports none of those (they are its residuals), and
a reader that must not miss a step has a person confirm each one.
"""

from __future__ import annotations

import ast
import builtins
import pathlib
import re
import sys
from dataclasses import dataclass
from typing import NamedTuple

from terp.arch._ast import parse
from terp.arch.rules._destructive_sql import (
    _CONSTRAINT,
    _DROP,
    _EXECUTING,
    _NOT_NULL,
    _RENAME,
    _TYPE,
    _classify_sql,
    _static_text,
)
from terp.arch.rules._support import ArchViolation, _rel
from terp.arch.rules.migrations import (
    _column_argument,
    _literal_name,
    _migration_files,
)

_MARKER = "'# arch-allow-no-destructive-migrations: <reason>'"

#: The list's word for an operation the reading cannot see into. It is not a kind of
#: finding: the rule reports the five kinds below, and an opaque operation is one of its
#: residuals, listed so that a reader can have a person confirm it.
_OPAQUE = "opaque"

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

#: The module an Alembic operation can be imported from by name.
_OPERATIONS_MODULE = "alembic.op"

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

#: For each call an operation's text names: the op-form position and keyword of the
#: table it acts on, and of its column (``None`` when the text names no column). A call
#: on a batch block's handle takes its table from the block, so its column sits one
#: position lower.
_SUBJECTS: dict[str, tuple[int, str, int | None, str | None]] = {
    "drop_table": (0, "table_name", None, None),
    "drop_column": (0, "table_name", 1, "column_name"),
    "rename_table": (0, "old_table_name", None, None),
    "alter_column": (0, "table_name", 1, "column_name"),
    **{attr: (spec[0], spec[1], None, None) for attr, spec in _CONSTRAINT_OPS.items()},
}

#: The packages a revision may call into without the call being opaque: Alembic,
#: SQLAlchemy, SQLModel and the standard library. They build the values an operation
#: takes, and a statement built with them is read where it is run, at ``execute(...)``.
_LIBRARIES = frozenset({"alembic", "sqlalchemy", "sqlmodel", *sys.stdlib_module_names})
#: The builtins whose call is read as running nothing: every one but the two that run text.
_INERT_BUILTINS = frozenset(
    name for name in dir(builtins) if not name.startswith("_")
) - {"exec", "eval"}
#: The operations read by name on any receiver, so that a call of one is never opaque.
_READ_OPERATIONS = frozenset(
    {"add_column", "create_table", *_SUBJECTS, *_EXECUTING}
)
#: The keywords an executing call takes its statement under, when not first.
_STATEMENT_KEYWORDS = frozenset({"sqltext", "statement"})
#: The methods of ``text(...)`` whose result is still that statement.
_TEXT_METHODS = frozenset({"bindparams", "columns", "execution_options"})

#: How an operation's text writes a table or column that is not a string literal.
_UNKNOWN = "?"
#: The most code points an operation's text holds, and the mark that ends a cut one.
_TEXT_LIMIT = 200
_CUT = "\u2026"
#: What an operation's text never holds: every control character and every character
#: Unicode counts as white space, listed rather than looked up so that the set cannot
#: move with a Python release. A run of them is written as one space.
_SEPARATORS_RE = re.compile(
    r"[\u0000-\u0020\u007f-\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+"
)


@dataclass(frozen=True)
class DestructiveOperation:
    """One destructive step a revision's ``upgrade()`` takes, as the rule finds it.

    ``ordinal`` is its place among the revision's operations, counted from 1 in source
    order. ``kind`` is the rule's word for it, one of ``drop``, ``rename``, ``type``,
    ``not-null`` and ``constraint``, each with one finding message, or ``opaque`` for a
    step the reading cannot see into, which no finding reports. ``line`` is the line its
    call starts on, which is where a finding is reported and where its marker is looked
    for. ``operation`` is one line naming the step; :func:`destructive_operations` gives
    its exact form.
    """

    ordinal: int
    kind: str
    line: int
    operation: str


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


def _subject(call: ast.Call, attr: str, batch_table: str | None, *, batch: bool) -> str:
    """``<attr> <table>`` or ``<attr> <table>.<column>``: what *call* acts on."""
    table_position, table_keyword, column_position, column_keyword = _SUBJECTS[attr]
    table = batch_table if batch else _literal(_argument(call, table_position, table_keyword))
    text = f"{attr} {_UNKNOWN if table is None else table}"
    if column_position is None:
        return text
    column = _literal(_argument(call, column_position - (1 if batch else 0), column_keyword))
    return f"{text}.{_UNKNOWN if column is None else column}"


def _one_line(text: str) -> str:
    """*text* as an operation's text: one line, trimmed, at most ``_TEXT_LIMIT`` long."""
    text = _SEPARATORS_RE.sub(" ", text).strip(" ")
    if len(text) <= _TEXT_LIMIT:
        return text
    return text[: _TEXT_LIMIT - 1].rstrip(" ") + _CUT


_Function = ast.FunctionDef | ast.AsyncFunctionDef


class _Call(NamedTuple):
    """One operation call the migration makes, as the rule reads it.

    ``attr`` is the operation's name. ``receiver`` is what it is called on, ``None`` for an
    operation imported by name, which acts like one called on ``op``. ``handles`` maps the
    ``as`` name of each enclosing ``batch_alter_table(...)`` block to that block's literal
    table (``None`` when the table is not a literal).
    """

    call: ast.Call
    attr: str
    receiver: ast.expr | None
    handles: dict[str, str | None]

    def batch(self) -> tuple[bool, str | None]:
        """Whether the call is made on a batch block's handle, and that block's table."""
        handle = self.receiver.id if isinstance(self.receiver, ast.Name) else None
        if handle is None or handle not in self.handles:
            return False, None
        return True, self.handles[handle]


class _Upgrade:
    """What one ``upgrade()`` knows about the rows its operations can meet."""

    def __init__(self, calls: list[_Call]) -> None:
        #: Tables this upgrade creates: they cannot hold a row yet.
        self.created: set[str] = set()
        #: Columns this upgrade adds nullable with no server default, per table: they
        #: hold only ``NULL`` on every existing row.
        self.null_only: dict[str | None, set[str]] = {}
        for entry in calls:
            if entry.attr == "create_table":
                name = _literal_name(entry.call)
                if name is not None:
                    self.created.add(name)
                continue
            column = _column_argument(entry.call) if entry.attr == "add_column" else None
            if column is None:
                continue
            table = _literal_name(entry.call, keyword="table_name") or entry.batch()[1]
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
    ) -> list[tuple[str, str]]:
        """The kind and the naming text of each destructive step *call* takes: one, or
        one for each destructive statement of a text that holds several, or none.

        *batch* says the call is made on a ``batch_alter_table`` block's handle, whose
        table is *batch_table* and whose operations therefore name no table themselves.
        Every other receiver is read in the op form, whatever it is called, so renaming
        the handle never unprotects the rule. An unresolvable table is one that may hold
        rows — the conservative direction, because the populated table is the case the
        rule exists for.
        """
        if attr in _EXECUTING:
            return [(kind, f"{attr}: {statement}") for kind, statement in _classify_sql(call)]
        if attr in {"drop_table", "drop_column"}:
            kind: str | None = _DROP
        elif attr == "rename_table":
            kind = _RENAME
        elif attr == "alter_column":
            kind = self._classify_alter(call, batch_table, batch=batch)
        elif attr in _CONSTRAINT_OPS:
            kind = self._classify_constraint(call, attr, batch_table, batch=batch)
        else:
            return []
        return [] if kind is None else [(kind, _subject(call, attr, batch_table, batch=batch))]

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


class _Revision:
    """What a revision binds at its top level, so a call out of ``upgrade()`` can be followed.

    ``functions`` holds every top-level function by name; a name defined twice keeps both,
    because which one a call meets is settled only when it runs. ``aliases`` holds each
    top-level ``name = other``, which makes *name* call what *other* calls: that is how
    ``upgrade = _up`` names the function the migration runs. ``operations`` holds each name
    imported from ``alembic.op``, by the name it is bound to and the operation it is.
    ``imported`` holds every other top-level import, by the name it binds and the package
    it comes from (empty for a relative import); ``classes`` the top-level classes; and
    ``bound`` every name the top level binds at all, however.
    """

    def __init__(self, tree: ast.Module) -> None:
        self.functions: dict[str, list[_Function]] = {}
        self.aliases: dict[str, list[str]] = {}
        self.operations: dict[str, str] = {}
        self.imported: dict[str, str] = {}
        self.classes: set[str] = set()
        self.bound: set[str] = set()
        for statement in tree.body:
            self.bound.update(_bound_names(statement))
            if isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef):
                self.functions.setdefault(statement.name, []).append(statement)
            elif isinstance(statement, ast.ClassDef):
                self.classes.add(statement.name)
            elif isinstance(statement, ast.Assign) and isinstance(statement.value, ast.Name):
                for target in statement.targets:
                    if isinstance(target, ast.Name):
                        self.aliases.setdefault(target.id, []).append(statement.value.id)
            elif (
                isinstance(statement, ast.ImportFrom)
                and statement.module == _OPERATIONS_MODULE
                and not statement.level
            ):
                for alias in statement.names:
                    self.operations[alias.asname or alias.name] = alias.name
            elif isinstance(statement, ast.ImportFrom):
                package = "" if statement.level else (statement.module or "").split(".")[0]
                for alias in statement.names:
                    self.imported[alias.asname or alias.name] = package
            elif isinstance(statement, ast.Import):
                for alias in statement.names:
                    self.imported[alias.asname or alias.name.split(".")[0]] = (
                        alias.name.split(".")[0]
                    )

    def inert(self, name: str) -> bool:
        """Whether a call of the bare *name* runs nothing the reading needs to see.

        A name imported from one of :data:`_LIBRARIES`, or a builtin other than ``exec``
        and ``eval`` that the revision does not rebind.
        """
        if name in self.imported:
            return self.imported[name] in _LIBRARIES
        return name not in self.bound and name in _INERT_BUILTINS

    def foreign(self, name: str) -> bool:
        """Whether *name* is a class of the revision or imported from outside the libraries."""
        return name in self.classes or self.imported.get(name, "alembic") not in _LIBRARIES

    def functions_named(self, name: str) -> list[_Function]:
        """Every top-level function a call of *name* can run, through any chain of aliases."""
        found: list[_Function] = []
        seen: set[str] = set()
        pending = [name]
        while pending:
            current = pending.pop()
            if current in seen:
                continue
            seen.add(current)
            found.extend(self.functions.get(current, ()))
            pending.extend(self.aliases.get(current, ()))
        return found

    def upgrades(self, tree: ast.Module) -> list[_Function]:
        """The functions the migration runs as its upgrade, each once.

        Every function named ``upgrade`` (as before, wherever it is defined), and every
        top-level function a top-level ``upgrade = ...`` names.
        """
        found: dict[int, _Function] = {}
        for function in ast.walk(tree):
            if isinstance(function, ast.FunctionDef | ast.AsyncFunctionDef):
                if function.name == "upgrade":
                    found.setdefault(id(function), function)
        for target in self.aliases.get("upgrade", ()):
            for function in self.functions_named(target):
                found.setdefault(id(function), function)
        return list(found.values())


def _bound_names(statement: ast.stmt) -> set[str]:
    """The names a top-level *statement* binds: a definition's, an import's, an assignment's."""
    if isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
        return {statement.name}
    if isinstance(statement, ast.Import | ast.ImportFrom):
        return {(alias.asname or alias.name).split(".")[0] for alias in statement.names}
    return {
        node.id
        for node in ast.walk(statement)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
    }


def _root(node: ast.expr) -> ast.Name | None:
    """The name an attribute chain (``a.b.c``) starts from, if it starts from one."""
    while isinstance(node, ast.Attribute):
        node = node.value
    return node if isinstance(node, ast.Name) else None


def _dotted(node: ast.expr) -> str:
    """``a.b.c`` for an attribute chain that starts from a name (see :func:`_root`)."""
    if isinstance(node, ast.Attribute):
        return f"{_dotted(node.value)}.{node.attr}"
    return node.id if isinstance(node, ast.Name) else _UNKNOWN


def _statement_is_read(call: ast.Call) -> bool:
    """Whether the statement an executing *call* runs has its text in the source.

    The statement is the call's first argument, or its ``sqltext=`` / ``statement=``. It
    is read when it is a string literal, an f-string or a ``+`` of strings, or ``text()``
    of one, ``.bindparams(...)``, ``.columns(...)`` and ``.execution_options(...)`` on it
    included.
    """
    node = call.args[0] if call.args else next(
        (k.value for k in call.keywords if k.arg in _STATEMENT_KEYWORDS), None
    )
    if node is None:
        return False
    if _static_text(node) is not None:
        return True
    while (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in _TEXT_METHODS
    ):
        node = node.func.value
    if not isinstance(node, ast.Call):
        return False
    callee = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
    text = node.args[0] if node.args else next(
        (k.value for k in node.keywords if k.arg == "text"), None
    )
    return callee == "text" and text is not None and _static_text(text) is not None


def _literal_getattr(node: ast.expr) -> tuple[ast.expr, str] | None:
    """``(receiver, name)`` for ``getattr(receiver, "name")``, a lookup by a literal name."""
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "getattr"
        and len(node.args) >= 2
    ):
        name = _literal(node.args[1])
        if name is not None:
            return node.args[0], name
    return None


def _calls(
    upgrade: _Function, revision: _Revision
) -> tuple[list[_Call], list[tuple[ast.Call, str]]]:
    """Every operation call the upgrade makes, in *upgrade* and in each function it reaches,
    and every call the reading cannot follow, with the text that names it.

    A call by name to a top-level function of the revision is followed into that function,
    and from there into each function it calls, each read once however often it is called,
    so a helper that calls itself, or two that call each other, cannot loop. A batch
    block's handle is known inside its block only, so a helper that is handed one reads
    its calls in the op form. A function defined inside a function that is read is read
    with it, so a call of it by name is followed too.
    """
    found: list[_Call] = []
    unread: list[tuple[ast.Call, str]] = []
    reached: list[_Function] = [upgrade]
    seen = {id(upgrade)}
    nested: set[str] = set()

    def method(call: ast.Call, receiver: ast.expr, attr: str) -> None:
        root = _root(receiver)
        if attr not in _READ_OPERATIONS and root is not None and revision.foreign(root.id):
            unread.append((call, f"call {_dotted(receiver)}.{attr}"))

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
        if isinstance(node, ast.Call):
            func = node.func
            looked_up = _literal_getattr(func)
            if isinstance(func, ast.Attribute):
                found.append(_Call(node, func.attr, func.value, handles))
                method(node, func.value, func.attr)
            elif looked_up is not None:
                found.append(_Call(node, looked_up[1], looked_up[0], handles))
                method(node, looked_up[0], looked_up[1])
            elif isinstance(func, ast.Name) and func.id in revision.operations:
                found.append(_Call(node, revision.operations[func.id], None, handles))
            elif isinstance(func, ast.Name) and revision.functions_named(func.id):
                for function in revision.functions_named(func.id):
                    if id(function) not in seen:
                        seen.add(id(function))
                        reached.append(function)
            elif isinstance(func, ast.Name):
                if not (revision.inert(func.id) or func.id in nested):
                    unread.append((node, f"call {func.id}"))
            elif isinstance(func, ast.Call) and getattr(func.func, "id", None) == "getattr":
                unread.append((node, "call getattr"))
            else:
                unread.append((node, f"call {_UNKNOWN}"))
        for child in ast.iter_child_nodes(node):
            walk(child, handles)

    index = 0
    while index < len(reached):
        function = reached[index]
        nested.update(
            inner.name
            for inner in ast.walk(function)
            if isinstance(inner, ast.FunctionDef | ast.AsyncFunctionDef) and inner is not function
        )
        walk(function, {})
        index += 1
    return found, unread


def check_no_destructive_migrations(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """A revision may not take a step that is safe only against an empty database.

    In ``upgrade()``, and in every top-level function of the revision it calls by name,
    transitively; on ``op``, a ``batch_alter_table`` block or any alias, as an operation
    imported by name from ``alembic.op``, or looked up with a literal ``getattr``: a drop
    (``drop_table`` / ``drop_column``), a rename (``rename_table``,
    ``alter_column(new_column_name=...)``), a type change (``alter_column(type_=...)``),
    a NOT NULL tightening of an existing column (``alter_column(nullable=False)``), and
    a constraint added to an existing table (``create_unique_constraint`` /
    ``create_check_constraint`` / ``create_foreign_key`` / ``create_primary_key`` /
    ``create_exclude_constraint`` / ``create_index(unique=True)``). The same steps
    smuggled through ``execute(...)`` / ``exec_driver_sql(...)`` as a statically
    readable statement are caught too: ``DROP TABLE`` / ``DROP COLUMN`` / ``DROP
    SCHEMA`` / ``TRUNCATE`` / ``DELETE FROM`` / ``ALTER TABLE ... DROP``, ``ALTER TABLE
    ... RENAME`` / ``RENAME TABLE``, ``ALTER COLUMN ... TYPE``, ``SET NOT NULL``, ``ADD
    CONSTRAINT`` (a check or a foreign key ``NOT VALID`` excepted), ``CREATE UNIQUE
    INDEX`` and ``VALIDATE CONSTRAINT``, each statement of a text on its own, split at
    every ``;`` outside a quoted string or name, a dollar-quoted body and a comment. A
    top-level ``upgrade = <function>`` makes that function the upgrade.

    Each operation is one violation whose message says what to do instead — expand,
    backfill, contract in a later release — and the contract step, reviewed, carries
    ``# arch-allow-no-destructive-migrations: <reason>`` on (or immediately above) the
    operation, counted against the app's escape-hatch budget, so every accepted risk is
    explicit, reviewable, greppable, and ratcheted. See the module docstring for the two
    exemptions, both about rows that cannot exist yet.

    The findings for a revision file are its :func:`destructive_operations` of the five
    kinds, one per operation, on the operation's line, with its kind's message. An
    ``opaque`` operation is not a finding: it is what the rule cannot read.
    """
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    for path in _migration_files(root):
        rel = _rel(path, root)
        violations.extend(
            ArchViolation(
                "no_destructive_migrations", rel, operation.line, _MESSAGES[operation.kind]
            )
            for operation in _operations(parse(path))
            if operation.kind != _OPAQUE
        )
    return violations


def destructive_operations(source: str) -> list[DestructiveOperation]:
    """Every destructive step the ``upgrade()`` of the revision *source* takes, and every
    step in it the reading cannot see into.

    The operations of the five kinds are the findings
    :func:`check_no_destructive_migrations` reports for the file, one for one and found
    by the same reading, the ones a ``# arch-allow-no-destructive-migrations`` marker
    excuses included: an excused step is still destructive, and a reader listing a
    release's steps must see it. An ``opaque`` operation is one the rule cannot read, and
    is never a finding; a reader that must not miss a step has a person confirm it. Nothing is
    read from ``downgrade()``, and a revision with no ``upgrade()`` has none; what an
    upgrade runs is read as the rule reads it (see the module docstring). The list
    is in source order, by the line and then the column each call starts at, and an
    operation's ``ordinal`` is its place in it, counted from 1. *source* is parsed with
    :func:`ast.parse` and is never imported or executed; source that does not parse
    raises :class:`SyntaxError`, as the rule does.

    An operation's text names the call that takes the step and what it acts on:

    * ``<call> <table>`` for ``drop_table``, ``rename_table``,
      ``create_unique_constraint``, ``create_primary_key``, ``create_foreign_key``,
      ``create_check_constraint``, ``create_exclude_constraint`` and ``create_index``,
      and ``<call> <table>.<column>`` for ``drop_column`` and ``alter_column``.
      ``<call>`` is the operation's name, whatever its receiver is called and whatever
      name it was imported under. On a
      ``batch_alter_table`` block's handle the table is the block's (its first
      argument, or ``table_name=``) and the column is the call's first argument, or
      ``column_name=``. Otherwise the table is the call's first argument, its second
      for the five ``create_*`` constraint calls and ``create_index``, or the keyword
      ``table_name=`` (``old_table_name=`` for ``rename_table``, ``source_table=`` for
      ``create_foreign_key``), and the column is the call's second argument, or
      ``column_name=``. A table or column that is not a string literal is written
      ``?``. For example ``drop_column invoice.legacy_ref`` or ``create_index customer``.
    * ``<call>: <statement>`` for ``execute`` and ``exec_driver_sql``, one for each
      destructive statement the call runs. The rule reads every text in the call's
      arguments, in order, where a string literal, an f-string or a ``+`` of strings is
      read whole wherever it sits in an argument (inside ``sa.text(...)`` too) and each
      interpolated part is written `` ? ``; it splits each text into statements at every
      ``;`` outside a quoted string or name, a dollar-quoted body and a comment, and the
      statement is the one it classified. For example ``execute: TRUNCATE invoice_run``.

    An ``opaque`` operation's text names what could not be read:

    * ``<call>: ?`` for an ``execute`` or ``exec_driver_sql`` whose statement (its first
      argument, or ``sqltext=`` / ``statement=``) has no text in the source: anything but
      a string literal, an f-string, a ``+`` of strings, or ``text()`` of one, with
      ``.bindparams(...)``, ``.columns(...)`` or ``.execution_options(...)`` on it. A
      statement in a variable, ``sa.text(name)`` and a SQLAlchemy construct such as
      ``invoice.delete()`` are each ``execute: ?``. It is listed beside whatever
      destructive statement the call's other arguments spell.
    * ``call <name>`` for a call by a bare name that the reading cannot follow: not an
      operation imported from ``alembic.op`` at the top level, not a top-level function
      of the revision (which is read as part of the upgrade, as is a function defined
      inside one that is read), not a name the top level imports from Alembic,
      SQLAlchemy, SQLModel or the standard library, and not a builtin other than
      ``exec`` and ``eval`` that the top level leaves unbound. A helper imported from
      another module, a top-level class, a callable held in a local or top-level name
      and a name nothing binds are each ``call <name>``.
    * ``call <name>.<attr>`` (the whole chain, ``call steps.legacy.contract``) for a
      method called on a name the top level imports from any other module, or on a
      top-level class of the revision, unless the method is one the rule reads by name
      (``add_column``, ``create_table``, the destructive operations, ``execute`` and
      ``exec_driver_sql``). ``getattr(steps, "contract")(...)`` reads as
      ``steps.contract(...)``.
    * ``call getattr`` for ``getattr(...)(...)`` whose name is not a literal, and
      ``call ?`` for a call of anything else: a subscript, a call's result, a lambda.

    Then, over the whole text, each run of characters from U+0000 to U+0020, U+007F to
    U+00A0, U+1680, U+2000 to U+200A, U+2028, U+2029, U+202F, U+205F and U+3000 becomes
    one space, and spaces at either end are removed. A text still longer than 200 code
    points keeps its first 199, less any trailing space, followed by ``…`` (U+2026). So
    the text is one line of 1 to 200 code points and holds no control character.
    """
    return _operations(ast.parse(source))


def _operations(tree: ast.Module) -> list[DestructiveOperation]:
    """The destructive steps of every upgrade in *tree*, in source order."""
    found: list[tuple[int, int, str, str]] = []
    revision = _Revision(tree)
    for function in revision.upgrades(tree):
        calls, unread = _calls(function, revision)
        upgrade = _Upgrade(calls)
        for entry in calls:
            batch, batch_table = entry.batch()
            for kind, text in upgrade.classify(entry.call, entry.attr, batch_table, batch=batch):
                found.append((entry.call.lineno, entry.call.col_offset, kind, text))
            if entry.attr in _EXECUTING and not _statement_is_read(entry.call):
                unread.append((entry.call, f"{entry.attr}: {_UNKNOWN}"))
        found.extend((call.lineno, call.col_offset, _OPAQUE, text) for call, text in unread)
    # Stable, so two calls that start at one place (a call made on another call's
    # result) keep the order the walk met them in.
    found.sort(key=lambda entry: entry[:2])
    return [
        DestructiveOperation(ordinal, kind, line, _one_line(text))
        for ordinal, (line, _, kind, text) in enumerate(found, start=1)
    ]
