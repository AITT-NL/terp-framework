"""The expand list (ADR 0185 decision 1): what an ``expand_only = True`` revision may do.

A revision marked expand-only promises that the previous release keeps working on the
schema it leaves. The list of operations that keeps that promise is closed, and this
module is its runtime half (the build-time half is ``terp.arch``'s
``check_expand_revisions_only_expand``, which reads the same list from source):

* ``create_table``, its own constraints and indexes (unique ones included), any
  foreign key from it having ``CASCADE`` or ``SET NULL``, and ``bulk_insert`` into it;
* ``add_column`` on an existing table that is nullable, has a ``server_default`` or is
  generated (``Computed``), declares no ``unique`` and no check, and whose only foreign
  key is ``SET NULL`` on a nullable column (inline, or a ``create_foreign_key`` over
  columns the same revision added);
* ``create_index`` that is not unique.

Everything else is off the list, ``execute`` and every other statement included. A
``batch_alter_table`` block is judged by the operations it records, and one created
with ``recreate="always"`` is off the list.

:class:`ExpandJudge` applies the list as the run executes, through three checks: each
operation as Alembic dispatches it, each statement the revision sends outside an
admitted operation, and (online, on PostgreSQL) the catalogue each step leaves. The
checks run in the process of the revision they judge, so they catch mistakes, not a
hostile revision; the backup before every ``migrate`` is the defence against that.
"""

from __future__ import annotations

import contextlib
import contextvars
import inspect
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

from alembic.operations import ops
from alembic.operations.base import AbstractOperations, Operations
from alembic.operations.batch import BatchOperationsImpl
from sqlalchemy import Column, ForeignKeyConstraint, event
from sqlmodel import SQLModel

from terp.migrations._catalogue import Snapshot, judge_catalogue, snapshot
from terp.migrations.errors import ExpandRevisionError

#: The module-level mark a revision declares itself expand-only with.
EXPAND_MARK = "expand_only"

#: Referential actions a foreign key from a table this revision creates may carry: a
#: delete the previous release makes then removes or detaches only rows it never reads.
_NEW_TABLE_ACTIONS = frozenset({"CASCADE", "SET NULL"})

#: The soft-delete trait's column (``terp.core.SoftDeleteMixin``): a target carrying it
#: is stamped rather than deleted, so neither action could ever fire (ADR 0133).
_SOFT_DELETE_COLUMN = "deleted_at"


def is_expand_only(module: Any) -> bool:
    """Whether a revision *module* declares ``expand_only = True`` (and nothing else counts)."""
    return getattr(module, EXPAND_MARK, False) is True


def _operation_name(operation: object) -> str:
    """``DropColumnOp`` -> ``drop_column``: the name an author wrote."""
    name = type(operation).__name__.removesuffix("Op")
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def _action(value: object) -> str:
    return str(value or "").strip().upper()


def _target_table(fullname: str) -> str:
    """The bare table name in a ``[schema.]table.column`` foreign-key target."""
    parts = fullname.split(".")
    return parts[-2] if len(parts) >= 2 else fullname


def is_soft_delete_table(table: str) -> bool:
    """Whether the model metadata declares *table* with the soft-delete column."""
    for candidate in SQLModel.metadata.tables.values():
        if candidate.name == table and _SOFT_DELETE_COLUMN in candidate.c:
            return True
    return False


@dataclass
class ExpandScope:
    """What one expand-only revision has done so far, for the rules that depend on it."""

    soft_delete: Callable[[str], bool] = is_soft_delete_table
    created: set[str] = field(default_factory=set)
    #: ``table -> {column: nullable}`` for each column ``add_column`` added.
    added: dict[str, dict[str, bool]] = field(default_factory=dict)


def _foreign_key_reason(
    target: str, action: str, *, allowed: frozenset[str], scope: ExpandScope, where: str
) -> str | None:
    if action not in allowed:
        spelled = action or "no ON DELETE (NO ACTION)"
        wanted = " or ".join(sorted(allowed))
        return f"a foreign key {where} onto {target!r} with {spelled}, where it needs {wanted}"
    if scope.soft_delete(_target_table(target) if "." in target else target):
        return (
            f"a foreign key {where} with {action} onto {target!r}, a soft-deleted table "
            "whose rows are never deleted, so the action could never fire"
        )
    return None


def _create_table_reason(operation: ops.CreateTableOp, scope: ExpandScope) -> str | None:
    where = f"from the new table {operation.table_name!r}"
    for item in operation.columns:
        if isinstance(item, Column):
            for key in item.foreign_keys:
                reason = _foreign_key_reason(
                    key.target_fullname,
                    _action(key.ondelete),
                    allowed=_NEW_TABLE_ACTIONS,
                    scope=scope,
                    where=where,
                )
                if reason:
                    return reason
        elif isinstance(item, ForeignKeyConstraint):
            reason = _foreign_key_reason(
                item.elements[0].target_fullname if item.elements else "?",
                _action(item.ondelete),
                allowed=_NEW_TABLE_ACTIONS,
                scope=scope,
                where=where,
            )
            if reason:
                return reason
    return None


def _add_column_reason(operation: ops.AddColumnOp, scope: ExpandScope) -> str | None:
    column = operation.column
    table = operation.table_name
    named = f"add_column {column.name!r} on {table!r}"
    if table in scope.created:
        return None
    if column.primary_key:
        return f"{named} as part of a primary key"
    if column.unique:
        return f"{named} with unique=True"
    if any(constraint.__class__.__name__ == "CheckConstraint" for constraint in column.constraints):
        return f"{named} with a check constraint"
    filled = (
        column.nullable
        or column.server_default is not None
        or column.computed is not None
    )
    if not filled:
        return f"{named}, NOT NULL with no server_default and not generated"
    for key in column.foreign_keys:
        if not column.nullable:
            return f"{named} with a foreign key on a NOT NULL column"
        reason = _foreign_key_reason(
            key.target_fullname,
            _action(key.ondelete),
            allowed=frozenset({"SET NULL"}),
            scope=scope,
            where=f"on {named}",
        )
        if reason:
            return reason
    scope.added.setdefault(table, {})[column.name] = bool(column.nullable)
    return None


def _create_foreign_key_reason(
    operation: ops.CreateForeignKeyOp, scope: ExpandScope
) -> str | None:
    action = _action(operation.kw.get("ondelete"))
    target = f"{operation.referent_table}.{','.join(operation.remote_cols)}"
    if operation.source_table in scope.created:
        return _foreign_key_reason(
            target,
            action,
            allowed=_NEW_TABLE_ACTIONS,
            scope=scope,
            where=f"from the new table {operation.source_table!r}",
        )
    added = scope.added.get(operation.source_table, {})
    if not operation.local_cols or not all(added.get(name) for name in operation.local_cols):
        return (
            f"create_foreign_key on {operation.source_table!r} over columns this revision "
            "did not add nullable"
        )
    return _foreign_key_reason(
        target,
        action,
        allowed=frozenset({"SET NULL"}),
        scope=scope,
        where=f"on {operation.source_table!r}",
    )


def _bulk_insert_table(operation: ops.BulkInsertOp) -> str:
    return str(getattr(operation.table, "name", ""))


def off_list_reason(operation: object, scope: ExpandScope) -> str | None:
    """Why *operation* is off the expand list, or ``None`` when the list admits it.

    *scope* carries what the revision did before it, and is updated with what this one
    adds: a table it creates, or a nullable column it adds, which later operations of the
    same revision may then build on.
    """
    if isinstance(operation, ops.CreateTableOp):
        reason = _create_table_reason(operation, scope)
        if reason is None:
            scope.created.add(operation.table_name)
        return reason
    if isinstance(operation, ops.AddColumnOp):
        return _add_column_reason(operation, scope)
    if isinstance(operation, ops.CreateIndexOp):
        if operation.unique and operation.table_name not in scope.created:
            return f"a unique index {operation.index_name!r} on the existing table {operation.table_name!r}"
        return None
    if isinstance(operation, ops.BulkInsertOp):
        table = _bulk_insert_table(operation)
        if table in scope.created:
            return None
        return f"bulk_insert into {table!r}, a table this revision did not create"
    if isinstance(operation, ops.CreateForeignKeyOp):
        return _create_foreign_key_reason(operation, scope)
    if isinstance(
        operation,
        ops.CreateUniqueConstraintOp | ops.CreateCheckConstraintOp | ops.CreatePrimaryKeyOp,
    ):
        table = getattr(operation, "table_name", "")
        if table in scope.created:
            return None
        return f"{_operation_name(operation)} on the existing table {table!r}"
    if isinstance(operation, ops.ExecuteSQLOp):
        return "an execute() statement"
    table = getattr(operation, "table_name", None)
    on = f" on {table!r}" if table else ""
    return f"{_operation_name(operation)}{on}"


def assert_operation_on_expand_list(
    operation: object, scope: ExpandScope, *, label: str, revision: str
) -> None:
    """Raise :class:`ExpandRevisionError` unless the expand list admits *operation*.

    The runtime half of ``backend/expand_revisions_only_expand``: the migration run
    calls it for each operation of an expand-only revision as Alembic dispatches it,
    before the operation's DDL runs (or is written, offline).
    """
    reason = off_list_reason(operation, scope)
    if reason is not None:
        raise ExpandRevisionError(label, revision, reason)


def generated_operations_on_list(upgrade_ops: Any) -> bool:
    """Whether *upgrade_ops* (an autogenerated script's) holds operations, all on the list.

    ``terp migrate make`` uses it to say where raising the mark is possible; it never
    raises the mark itself (decision 1: the author raises it).
    """
    found: list[object] = []

    def walk(container: Any) -> None:
        for item in container.ops:
            if isinstance(item, ops.OpContainer):
                walk(item)
            else:
                found.append(item)

    walk(upgrade_ops)
    scope = ExpandScope()
    return bool(found) and all(off_list_reason(item, scope) is None for item in found)


# --------------------------------------------------------------------------- #
# The runtime judge                                                            #
# --------------------------------------------------------------------------- #


@dataclass
class _Step:
    label: str
    revision: str
    expand: bool
    scope: ExpandScope = field(default_factory=ExpandScope)
    in_upgrade: bool = False
    admitted: int = 0
    before: Snapshot | None = None


_ACTIVE: contextvars.ContextVar[ExpandJudge | None] = contextvars.ContextVar(
    "terp_expand_judge", default=None
)
_ORIGINAL_INVOKE = AbstractOperations.invoke
_ORIGINAL_BATCH = Operations.batch_alter_table
_ORIGINAL_FLUSH = BatchOperationsImpl.flush
_BATCH_SIGNATURE = inspect.signature(_ORIGINAL_BATCH)
_installed = 0


def _judged_invoke(self: AbstractOperations, operation: Any) -> Any:
    judge = _ACTIVE.get()
    if judge is None:
        return _ORIGINAL_INVOKE(self, operation)
    return judge.invoke(operation, lambda: _ORIGINAL_INVOKE(self, operation))


def _judged_batch(self: Operations, *args: Any, **kw: Any) -> Any:
    judge = _ACTIVE.get()
    if judge is not None:
        bound = _BATCH_SIGNATURE.bind(self, *args, **kw)
        judge.batch(str(bound.arguments["table_name"]), bound.arguments.get("recreate", "auto"))
    return _ORIGINAL_BATCH(self, *args, **kw)


def _judged_flush(self: BatchOperationsImpl) -> None:
    judge = _ACTIVE.get()
    if judge is None:
        return _ORIGINAL_FLUSH(self)
    with judge.admitted():
        return _ORIGINAL_FLUSH(self)


@contextlib.contextmanager
def _patched() -> Iterator[None]:
    """Route Alembic's dispatch through the active judge for the length of one run."""
    global _installed
    if _installed == 0:
        AbstractOperations.invoke = _judged_invoke  # type: ignore[method-assign]
        Operations.batch_alter_table = _judged_batch  # type: ignore[method-assign]
        BatchOperationsImpl.flush = _judged_flush  # type: ignore[method-assign]
    _installed += 1
    try:
        yield
    finally:
        _installed -= 1
        if _installed == 0:
            AbstractOperations.invoke = _ORIGINAL_INVOKE  # type: ignore[method-assign]
            Operations.batch_alter_table = _ORIGINAL_BATCH  # type: ignore[method-assign]
            BatchOperationsImpl.flush = _ORIGINAL_FLUSH  # type: ignore[method-assign]


def _statement_text(statement: Any) -> str:
    text = getattr(statement, "text", None)
    if not isinstance(text, str):
        try:
            text = str(statement)
        except Exception:  # pragma: no cover - a construct that cannot render itself
            text = type(statement).__name__
    return " ".join(text.split())[:200]


class ExpandJudge:
    """Applies the expand list to one package's migration run (ADR 0185 decision 1).

    Three checks, each refusing before the thing it judges runs where it can:

    * every operation of an expand-only revision, as Alembic dispatches it;
    * every statement such a revision sends outside an admitted operation, online
      through the connection's ``before_cursor_execute`` and offline through the
      implementation that writes the script (``op.get_bind()`` returns a connection in
      both modes, and in ``--sql`` mode it writes straight into the script);
    * online on PostgreSQL, the catalogue the step left, read inside the step's own
      transaction after its version update, which is how a batch flush that rebuilt its
      table is judged.
    """

    def __init__(self, label: str, *, catalogue: bool) -> None:
        self.label = label
        self.catalogue = catalogue
        self.step: _Step | None = None
        #: The run's connection while :meth:`active` holds it (online only).
        self._connection: Any = None

    # -- the per-revision wrapper -------------------------------------------------
    def wrap(self, script: Any) -> None:
        """Wrap *script*'s ``upgrade()`` so the judge knows where a step starts."""
        module = script.module
        original = getattr(module, "upgrade", None)
        if original is None or getattr(original, "_terp_judged", False):
            return
        judge = self

        def upgrade(*args: Any, **kw: Any) -> Any:
            with judge.revision(script):
                return original(*args, **kw)

        upgrade._terp_judged = True  # type: ignore[attr-defined]
        module.upgrade = upgrade

    @contextlib.contextmanager
    def revision(self, script: Any) -> Iterator[None]:
        expand = is_expand_only(script.module)
        step = _Step(self.label, script.revision, expand)
        self.step = step
        if expand:
            parents = script._normalized_down_revisions
            if len(parents) > 1:
                raise ExpandRevisionError(self.label, script.revision, "a merge revision")
            if self.catalogue and self._connection is not None:
                step.before = snapshot(self._connection)
        step.in_upgrade = True
        try:
            yield
        finally:
            step.in_upgrade = False

    # -- the hooks the patched dispatch calls -------------------------------------
    def _judging(self) -> _Step | None:
        step = self.step
        if step is None or not step.expand or not step.in_upgrade:
            return None
        return step

    def invoke(self, operation: Any, call: Callable[[], Any]) -> Any:
        step = self._judging()
        if step is None:
            return call()
        assert_operation_on_expand_list(
            operation, step.scope, label=step.label, revision=step.revision
        )
        with self.admitted():
            return call()

    def batch(self, table: str, recreate: str) -> None:
        step = self._judging()
        if step is not None and recreate == "always":
            raise ExpandRevisionError(
                step.label, step.revision, f'batch_alter_table({table!r}, recreate="always")'
            )

    @contextlib.contextmanager
    def admitted(self) -> Iterator[None]:
        step = self.step
        if step is None:
            yield
            return
        step.admitted += 1
        try:
            yield
        finally:
            step.admitted -= 1

    def statement(self, statement: Any) -> None:
        step = self._judging()
        if step is not None and step.admitted == 0:
            raise ExpandRevisionError(
                step.label,
                step.revision,
                f"a statement sent outside an operation ({_statement_text(statement)})",
            )

    # -- the step's end -----------------------------------------------------------
    def finish(self, revision: str) -> bool | None:
        """At ``on_version_apply``: judge the catalogue, and say whether *revision* is expand.

        ``None`` when the step was not one this judge saw start (a stamp).
        """
        step = self.step
        if step is None or step.revision != revision:
            return None
        if step.expand and step.before is not None and self._connection is not None:
            refusal = judge_catalogue(step.before, snapshot(self._connection))
            if refusal is not None:
                raise ExpandRevisionError(step.label, step.revision, refusal, after=True)
        return step.expand

    # -- installation -------------------------------------------------------------
    @contextlib.contextmanager
    def active(self, *, connection: Any = None, impl: Any = None) -> Iterator[ExpandJudge]:
        """Judge the run inside this block: online through *connection*, offline through *impl*."""
        self._connection = connection
        token = _ACTIVE.set(self)
        listener = None
        original_exec = None
        if connection is not None:

            def listener(conn: Any, cursor: Any, statement: str, *rest: Any) -> None:
                self.statement(statement)

            event.listen(connection, "before_cursor_execute", listener)
        if impl is not None:
            original_exec = impl._exec

            def judged_exec(construct: Any, *args: Any, **kw: Any) -> Any:
                self.statement(construct)
                return original_exec(construct, *args, **kw)

            impl._exec = judged_exec
        try:
            with _patched():
                yield self
        finally:
            _ACTIVE.reset(token)
            if listener is not None:
                event.remove(connection, "before_cursor_execute", listener)
            if original_exec is not None:
                impl._exec = original_exec
            self._connection = None


__all__ = [
    "EXPAND_MARK",
    "ExpandJudge",
    "ExpandScope",
    "assert_operation_on_expand_list",
    "generated_operations_on_list",
    "is_expand_only",
    "is_soft_delete_table",
    "off_list_reason",
]
