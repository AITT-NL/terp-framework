"""What one upgrade runs: the calls ``no_destructive_migrations`` reads, wherever they are made.

A migration runs more than ``upgrade()`` spells itself: a function of the same revision it
calls, an operation imported by name, one looked up by a literal name, and whatever a
top-level ``upgrade = ...`` names. This module reads a revision's top level for those
bindings and walks every function the upgrade reaches, so the rule classifies every
operation call the migration makes, and names each call it cannot follow. Private to
:mod:`terp.arch.rules.destructive_migrations`, which owns the kinds and their messages.
"""

from __future__ import annotations

import ast
import builtins
import sys
from typing import NamedTuple

from terp.arch.rules.migrations import _literal_name

#: The module an Alembic operation can be imported from by name.
_OPERATIONS_MODULE = "alembic.op"


#: The packages a revision may call into without the call being opaque: Alembic,
#: SQLAlchemy, SQLModel and the standard library. They build the values an operation
#: takes, and a statement built with them is read where it is run, at ``execute(...)``.
_LIBRARIES = frozenset({"alembic", "sqlalchemy", "sqlmodel", *sys.stdlib_module_names})
#: The builtins whose call is read as running nothing: every one but the two that run text.
_INERT_BUILTINS = frozenset(
    name for name in dir(builtins) if not name.startswith("_")
) - {"exec", "eval"}
#: How an operation's text writes a table or column that is not a string literal.
_UNKNOWN = "?"


def _literal(node: ast.expr | None) -> str | None:
    """*node*'s value when it is a string literal."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


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
    and every call by a name or a value the reading cannot follow, with the text that
    names it. A method's call is an operation call here; whether its receiver is one the
    reading can see into is the rule's to judge (:meth:`_Revision.foreign`).

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
            elif looked_up is not None:
                found.append(_Call(node, looked_up[1], looked_up[0], handles))
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
