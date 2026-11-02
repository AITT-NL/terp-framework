"""The expand list, read from source (ADR 0185 decision 1).

A revision may declare ``expand_only = True``: a promise that the previous release
keeps working on the schema it leaves, which is what lets a release roll back without
a restore. The operations that keep that promise are a closed list, and this rule holds
a raised mark to it before the release is built; ``terp.migrations`` holds the same list
while the revision runs (``assert_operation_on_expand_list``).

On the list:

* ``create_table``, with everything that is its own (constraints and indexes, unique
  ones included), a foreign key from it only with ``CASCADE`` or ``SET NULL``, and
  ``bulk_insert`` into it;
* ``add_column`` on an existing table that is nullable, carries a ``server_default`` or
  is generated (``Computed``), and declares no ``unique``, no check and no foreign key
  but a ``SET NULL`` one on a nullable column (inline, or a ``create_foreign_key`` over
  columns the same revision adds);
* ``create_index`` that is not unique;
* a ``batch_alter_table`` block, judged by what it holds, unless ``recreate="always"``.

Everything else is off: every drop, rename, type change and tightening; a unique or
check constraint, unique index or primary key on an existing table; ``execute``, a
statement sent through ``op.get_bind()``, and any data write to a table that already
exists; and a merge revision. There is no opt-out marker: a revision that needs one is
a contract revision, and saying so costs only restore-free rollback for its release.
"""

from __future__ import annotations

import ast
import pathlib
from collections.abc import Iterator

from terp.arch._ast import parse
from terp.arch.rules._support import ArchViolation, _rel
from terp.arch.rules.migrations import (
    _column_argument,
    _literal_name,
    _migration_files,
    _module_constant,
    _parent_revisions,
)
from terp.arch.rules.references import _soft_delete_tables

RULE = "expand_revisions_only_expand"

#: The module-level mark, and the only value that raises it.
_MARK = "expand_only"

#: Calls that send a statement or reach past Alembic's dispatch, whatever the receiver.
_STATEMENTS = frozenset({"execute", "exec_driver_sql", "get_bind", "invoke", "run_async"})

#: Alembic operations no expand-only revision may hold, whatever the receiver.
_OFF_THE_LIST = frozenset(
    {
        "alter_column",
        "create_exclude_constraint",
        "create_table_comment",
        "drop_column",
        "drop_constraint",
        "drop_index",
        "drop_table",
        "drop_table_comment",
        "rename_table",
        "register_operation",
        "implementation_for",
    }
)

#: Operations the list may admit, each judged below.
_JUDGED = frozenset(
    {
        "add_column",
        "batch_alter_table",
        "bulk_insert",
        "create_check_constraint",
        "create_foreign_key",
        "create_index",
        "create_primary_key",
        "create_table",
        "create_unique_constraint",
    }
)

#: What the ``op`` handle or a batch handle may also be asked for: no statement at all.
_HELPERS = frozenset({"f", "get_context", "inline_literal"})

_NEW_TABLE_ACTIONS = frozenset({"CASCADE", "SET NULL"})


def _mark(tree: ast.Module) -> tuple[object, int] | None:
    """The module-level mark's value and line: ``True``, ``False``, or ``...`` when computed."""
    for statement in tree.body:
        targets: list[ast.expr] = []
        if isinstance(statement, ast.Assign):
            targets = list(statement.targets)
        elif isinstance(statement, ast.AnnAssign):
            targets = [statement.target]
        if any(isinstance(target, ast.Name) and target.id == _MARK for target in targets):
            value = getattr(statement, "value", None)
            if isinstance(value, ast.Constant) and isinstance(value.value, bool):
                return value.value, statement.lineno
            return ..., statement.lineno
    return None


def _callee(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    if isinstance(call.func, ast.Name):
        return call.func.id
    return None


def _keyword(call: ast.Call, name: str) -> ast.expr | None:
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _literal(node: ast.expr | None) -> object:
    """*node*'s literal value, or the sentinel ``...`` when it is not one."""
    if node is None:
        return None
    try:
        return ast.literal_eval(node)
    except ValueError:
        return ...


def _argument(call: ast.Call, position: int, keyword: str) -> ast.expr | None:
    if len(call.args) > position:
        return call.args[position]
    return _keyword(call, keyword)


def _action(call: ast.Call) -> str:
    value = _literal(_keyword(call, "ondelete"))
    return value.upper() if isinstance(value, str) else ""


def _target_table(target: object) -> str | None:
    if isinstance(target, str) and "." in target:
        return target.rsplit(".", 2)[-2]
    return None


class _Revision:
    """One marked revision's ``upgrade()``, read the way the run will execute it."""

    def __init__(self, function: ast.FunctionDef | ast.AsyncFunctionDef, soft: frozenset[str]) -> None:
        self.function = function
        self.soft = soft
        self.created: set[str] = set()
        self.created_names: set[str] = set()
        self.added: dict[str, dict[str, bool]] = {}
        self.batches: dict[str, str | None] = {}
        self._collect()

    # -- what the revision creates and adds, before anything is judged -------------
    def _collect(self) -> None:
        for node in ast.walk(self.function):
            if isinstance(node, ast.With):
                for item in node.items:
                    context = item.context_expr
                    if (
                        isinstance(context, ast.Call)
                        and _callee(context) == "batch_alter_table"
                        and isinstance(item.optional_vars, ast.Name)
                    ):
                        self.batches[item.optional_vars.id] = _literal_name(
                            context, keyword="table_name"
                        )
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                if _callee(node.value) == "create_table":
                    self.created_names.update(
                        target.id for target in node.targets if isinstance(target, ast.Name)
                    )
            if isinstance(node, ast.Call) and _callee(node) == "create_table":
                name = _literal_name(node, keyword="table_name")
                if name is not None:
                    self.created.add(name)

    def _table(self, call: ast.Call, position: int) -> str | None:
        """The table *call* acts on: its own argument, or the batch block's."""
        receiver = call.func.value if isinstance(call.func, ast.Attribute) else None
        if isinstance(receiver, ast.Name) and receiver.id in self.batches:
            return self.batches[receiver.id]
        value = _literal(_argument(call, position, "table_name"))
        return value if isinstance(value, str) else None

    def _batch(self, call: ast.Call) -> bool:
        receiver = call.func.value if isinstance(call.func, ast.Attribute) else None
        return isinstance(receiver, ast.Name) and receiver.id in self.batches

    def _foreign_key(self, target: str | None, action: str, allowed: frozenset[str], where: str) -> str | None:
        if action not in allowed:
            return (
                f"a foreign key {where} with {action or 'no ondelete'}, where it needs "
                f"{' or '.join(sorted(allowed))}"
            )
        if target is not None and target in self.soft:
            return f"a foreign key {where} onto the soft-deleted table {target!r}"
        return None

    # -- the judgments -----------------------------------------------------------
    def _create_table(self, call: ast.Call) -> str | None:
        name = _literal_name(call, keyword="table_name")
        where = f"from the new table {name!r}"
        for node in ast.walk(call):
            if not isinstance(node, ast.Call):
                continue
            if _callee(node) == "ForeignKey":
                reason = self._foreign_key(
                    _target_table(_literal(node.args[0]) if node.args else None),
                    _action(node),
                    _NEW_TABLE_ACTIONS,
                    where,
                )
            elif _callee(node) == "ForeignKeyConstraint":
                targets = _literal(_argument(node, 1, "refcolumns"))
                first = targets[0] if isinstance(targets, list | tuple) and targets else None
                reason = self._foreign_key(_target_table(first), _action(node), _NEW_TABLE_ACTIONS, where)
            else:
                continue
            if reason:
                return reason
        return None

    def _column(self, call: ast.Call, table: str | None) -> tuple[str | None, str | None, bool]:
        """``(refusal, column name, nullable)`` for an ``add_column``'s inline column."""
        column = _column_argument(call)
        if column is None:
            return "add_column with a column the check cannot read here", None, False
        name = _literal(column.args[0]) if column.args else _literal(_keyword(column, "name"))
        named = f"add_column {name!r} on {table!r}" if isinstance(name, str) else "add_column"
        primary = _literal(_keyword(column, "primary_key"))
        if primary not in (None, False):
            return f"{named} as part of a primary key", None, False
        unique = _literal(_keyword(column, "unique"))
        if unique not in (None, False):
            return f"{named} with unique", None, False
        nullable = _literal(_keyword(column, "nullable"))
        is_nullable = nullable is None or nullable is True
        default = _keyword(column, "server_default")
        generated = any(
            isinstance(arg, ast.Call) and _callee(arg) == "Computed" for arg in column.args
        )
        if not (is_nullable or (default is not None and _literal(default) is not None) or generated):
            return f"{named}, NOT NULL with no server_default and not generated", None, False
        for arg in column.args:
            if not isinstance(arg, ast.Call):
                continue
            if _callee(arg) == "CheckConstraint":
                return f"{named} with a check constraint", None, False
            if _callee(arg) == "ForeignKey":
                if not is_nullable:
                    return f"{named} with a foreign key on a NOT NULL column", None, False
                reason = self._foreign_key(
                    _target_table(_literal(arg.args[0]) if arg.args else None),
                    _action(arg),
                    frozenset({"SET NULL"}),
                    f"on {named}",
                )
                if reason:
                    return reason, None, False
        return None, name if isinstance(name, str) else None, is_nullable

    def judge(self, call: ast.Call) -> str | None:
        """Why *call* is off the list, or ``None`` (an unrelated call is ``None`` too)."""
        name = _callee(call)
        if name in _STATEMENTS:
            return f"{name}(), which sends a statement the expand list does not judge"
        if name in _OFF_THE_LIST:
            return name
        receiver = call.func.value if isinstance(call.func, ast.Attribute) else None
        handle = isinstance(receiver, ast.Name) and (receiver.id == "op" or receiver.id in self.batches)
        if name not in _JUDGED:
            if handle and name not in _HELPERS:
                return f"{name}, an operation the expand list does not name"
            return None
        batch = self._batch(call)
        if name == "create_table":
            return self._create_table(call)
        if name == "batch_alter_table":
            recreate = _literal(_argument(call, 2, "recreate"))
            if recreate not in (None, "auto", "never"):
                return f'batch_alter_table with recreate={recreate if recreate is not ... else "<computed>"!r}'
            return None
        if name == "add_column":
            table = self._table(call, 0)
            if table is not None and table in self.created:
                return None
            refusal, column, _nullable = self._column(call, table)
            return refusal
        if name == "create_index":
            table = self._table(call, 1)
            unique = _literal(_keyword(call, "unique"))
            if unique in (None, False) or (table is not None and table in self.created):
                return None
            return f"a unique index on the existing table {table!r}"
        if name == "bulk_insert":
            target = call.args[0] if call.args else _keyword(call, "table")
            if isinstance(target, ast.Name) and target.id in self.created_names:
                return None
            if isinstance(target, ast.Call) and target.args:
                literal = _literal(target.args[0])
                if isinstance(literal, str) and literal in self.created:
                    return None
            return "bulk_insert into a table this revision does not create"
        if name == "create_foreign_key":
            return self._create_foreign_key(call, batch)
        table = self._table(call, 1)
        if table is not None and table in self.created:
            return None
        return f"{name} on the existing table {table!r}"

    def _create_foreign_key(self, call: ast.Call, batch: bool) -> str | None:
        offset = -1 if batch else 0
        source = self._table(call, 1)
        referent = _literal(_argument(call, 2 + offset, "referent_table"))
        local = _literal(_argument(call, 3 + offset, "local_cols"))
        referent_name = referent if isinstance(referent, str) else None
        if source is not None and source in self.created:
            return self._foreign_key(referent_name, _action(call), _NEW_TABLE_ACTIONS, f"from the new table {source!r}")
        added = self.added.get(source or "", {})
        if not isinstance(local, list | tuple) or not local or not all(added.get(c) for c in local):
            return f"create_foreign_key on {source!r} over columns this revision does not add nullable"
        return self._foreign_key(referent_name, _action(call), frozenset({"SET NULL"}), f"on {source!r}")

    def violations(self) -> Iterator[tuple[int, str]]:
        # The columns this revision adds, before any create_foreign_key over them is read.
        for node in ast.walk(self.function):
            if isinstance(node, ast.Call) and _callee(node) == "add_column":
                table = self._table(node, 0)
                refusal, column, nullable = self._column(node, table)
                if refusal is None and table is not None and column is not None:
                    self.added.setdefault(table, {})[column] = nullable
        # One report per line: ``op.get_bind().execute(...)`` is one statement, not two.
        reported: set[int] = set()
        for node in ast.walk(self.function):
            if isinstance(node, ast.Call):
                reason = self.judge(node)
                if reason is not None and node.lineno not in reported:
                    reported.add(node.lineno)
                    yield node.lineno, reason


def check_expand_revisions_only_expand(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """A revision marked ``expand_only = True`` holds only operations on the expand list.

    The build-time half of ADR 0185 decision 1. The mark promises that the previous
    release keeps running on the schema the revision leaves; an operation off the list
    breaks that promise, and the release would then need a restore to roll back, which
    nobody finds out until the rollback. Reading each ``Column`` the revision adds and
    each batch block's ``recreate``, this refuses the revision before it ships. There is
    no opt-out marker, and a ``no_destructive_migrations`` marker excuses nothing here:
    a revision that needs one is a contract revision, so set ``expand_only = False``.
    """
    root = pathlib.Path(app_root)
    soft = _soft_delete_tables(root)
    violations: list[ArchViolation] = []
    for path in _migration_files(root):
        tree = parse(path)
        mark = _mark(tree)
        if mark is None or mark[0] is False:
            continue
        rel = _rel(path, root)
        found: list[tuple[int, str]] = []
        if mark[0] is ...:
            # The run reads whatever the expression evaluates to; the check cannot, so a
            # mark it cannot read is refused rather than taken for either answer.
            violations.append(
                ArchViolation(
                    RULE,
                    rel,
                    mark[1],
                    "expand_only is not the literal True or False, so this check cannot "
                    "read the promise the migration run will hold it to (ADR 0185); write "
                    "expand_only = True or expand_only = False",
                )
            )
            continue
        down = _module_constant(tree, "down_revision")
        if down is not None and len(_parent_revisions(down[0])) > 1:
            found.append((down[1], "a merge revision"))
        for function in tree.body:
            if isinstance(function, ast.FunctionDef | ast.AsyncFunctionDef) and function.name == "upgrade":
                found.extend(_Revision(function, soft).violations())
        violations.extend(
            ArchViolation(
                RULE,
                rel,
                line,
                f"this revision is marked expand_only = True and holds {what}, which is not "
                "on the expand list (ADR 0185): the previous release could not be trusted to "
                "run on the schema it leaves. Move that step to a later release's revision, "
                "or set expand_only = False, which makes this release's rollback "
                "restore-based. No marker excuses it.",
            )
            for line, what in found
        )
    return violations


__all__ = ["check_expand_revisions_only_expand"]
