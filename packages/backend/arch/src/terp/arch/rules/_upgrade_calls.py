"""What one upgrade runs: the calls ``no_destructive_migrations`` reads, wherever they are made.

A migration runs more than ``upgrade()`` spells itself: a function of the same revision it
calls, an operation imported by name, one looked up by a literal name, and whatever a
top-level ``upgrade = ...`` names. This module reads a revision's top level for those
bindings and walks every function the upgrade reaches, so the rule classifies every
operation call the migration makes. Private to
:mod:`terp.arch.rules.destructive_migrations`, which owns the kinds and their messages.
"""

from __future__ import annotations

import ast
from typing import NamedTuple

from terp.arch.rules.migrations import _literal_name

#: The module an Alembic operation can be imported from by name.
_OPERATIONS_MODULE = "alembic.op"


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
    """

    def __init__(self, tree: ast.Module) -> None:
        self.functions: dict[str, list[_Function]] = {}
        self.aliases: dict[str, list[str]] = {}
        self.operations: dict[str, str] = {}
        for statement in tree.body:
            if isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef):
                self.functions.setdefault(statement.name, []).append(statement)
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


def _calls(upgrade: _Function, revision: _Revision) -> list[_Call]:
    """Every operation call the upgrade makes, in *upgrade* and in each function it reaches.

    A call by name to a top-level function of the revision is followed into that function,
    and from there into each function it calls, each read once however often it is called,
    so a helper that calls itself, or two that call each other, cannot loop. A batch
    block's handle is known inside its block only, so a helper that is handed one reads
    its calls in the op form.
    """
    found: list[_Call] = []
    reached: list[_Function] = [upgrade]
    seen = {id(upgrade)}

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
            elif isinstance(func, ast.Name):
                for function in revision.functions_named(func.id):
                    if id(function) not in seen:
                        seen.add(id(function))
                        reached.append(function)
        for child in ast.iter_child_nodes(node):
            walk(child, handles)

    index = 0
    while index < len(reached):
        walk(reached[index], {})
        index += 1
    return found
