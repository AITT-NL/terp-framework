"""The composition rule: the modules an app mounts are the same in every environment.

``create_app`` mounts the modules it is handed, and the access check records who can reach
each route by composing the app (ADR 0139, ADR 0209). A module added to that list under a
condition is mounted where the condition holds and nowhere else, so the app serves routes in
one environment that the check, run in another, never saw. :func:`check_module_list_is_unconditional`
follows the list handed to ``create_app`` back through the file that builds it and refuses
every place it is decided under a condition (ADR 0211).

It reads one file at a time. A list built in another module, and a module object that is
itself ``None`` under a condition, are outside it and recorded as the rule's residuals.
"""

from __future__ import annotations

import ast
import pathlib
from collections.abc import Iterator

from terp.arch._ast import iter_python_files, parse
from terp.arch.rules._support import ArchViolation, _rel

_RULE = "module_list_is_unconditional"
#: The statements under which whatever they hold runs only sometimes.
_CONDITIONAL = (ast.If, ast.While, ast.For, ast.AsyncFor, ast.Try, ast.Match)
#: The calls that change a list in place.
_MUTATORS = frozenset({"append", "extend", "insert", "remove", "pop", "clear"})
_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
_REMEDY = (
    "an app mounts the same modules in every environment, so the routes it serves and the "
    "access check's record of them never depend on a setting: mount the module always, and "
    "let its routes refuse while it is not configured"
)


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    return {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}


class _File:
    """One parsed file: who holds each node, and the functions it defines by name."""

    def __init__(self, tree: ast.Module) -> None:
        self.tree = tree
        self.parents = _parents(tree)
        self.functions = {node.name: node for node in ast.walk(tree) if isinstance(node, _FUNCTIONS)}
        self.found: dict[int, str] = {}
        self._seen: set[tuple[int, int]] = set()

    def scope_of(self, node: ast.AST) -> ast.AST:
        """The function that holds *node*, or the module."""
        current = self.parents.get(node)
        while current is not None and not isinstance(current, _FUNCTIONS):
            current = self.parents.get(current)
        return current or self.tree

    def condition_over(self, node: ast.AST, scope: ast.AST) -> ast.AST | None:
        """The nearest conditional statement between *node* and its *scope*, if any."""
        current = self.parents.get(node)
        while current is not None and current is not scope:
            if isinstance(current, _CONDITIONAL):
                return current
            current = self.parents.get(current)
        return None

    def refuse(self, node: ast.AST, why: str) -> None:
        self.found.setdefault(node.lineno, f"the modules handed to create_app {why}; {_REMEDY}")

    # ---- following the list back -----------------------------------------------------

    def trace(self, expr: ast.expr, scope: ast.AST) -> None:
        """Refuse every condition the value of *expr* is decided under, within this file."""
        key = (id(expr), id(scope))
        if key in self._seen:
            return
        self._seen.add(key)
        if isinstance(expr, ast.IfExp):
            self.refuse(expr, "are chosen by a conditional expression")
        elif isinstance(expr, ast.Starred):
            self.trace(expr.value, scope)
        elif isinstance(expr, ast.List | ast.Tuple | ast.Set):
            for element in expr.elts:
                self.trace(element, scope)
        elif isinstance(expr, ast.ListComp | ast.SetComp | ast.GeneratorExp):
            if any(generator.ifs for generator in expr.generators):
                self.refuse(expr, "are filtered by a comprehension's condition")
        elif isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Add):
            self.trace(expr.left, scope)
            self.trace(expr.right, scope)
        elif isinstance(expr, ast.Call):
            self._call(expr, scope)
        elif isinstance(expr, ast.Name):
            self._name(expr.id, scope)

    def _call(self, call: ast.Call, scope: ast.AST) -> None:
        name = call.func.id if isinstance(call.func, ast.Name) else None
        if name == "filter":
            self.refuse(call, "are filtered")
        elif name in ("list", "tuple", "sorted") and call.args:
            self.trace(call.args[0], scope)
        elif name in self.functions:  # a helper of this file that returns the list
            helper = self.functions[name]
            for node in ast.walk(helper):
                if isinstance(node, ast.Return) and node.value is not None and self.scope_of(node) is helper:
                    if self.condition_over(node, helper) is not None:
                        self.refuse(node, "are returned under a condition")
                    self.trace(node.value, helper)

    def _name(self, name: str, scope: ast.AST) -> None:
        if isinstance(scope, _FUNCTIONS) and self._parameter(name, scope):
            return
        for node in ast.walk(scope):
            if self.scope_of(node) is not scope:
                continue
            value = self._written(node, name)
            if value is None:
                continue
            statement, written = value
            if self.condition_over(statement, scope) is not None:
                self.refuse(statement, f"are changed under a condition ({name})")
            for expr in written:
                self.trace(expr, scope)

    def _written(self, node: ast.AST, name: str) -> tuple[ast.AST, list[ast.expr]] | None:
        """The statement that writes the list *name*, and the values it writes."""
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            return node, [node.value]
        if isinstance(node, ast.AnnAssign | ast.AugAssign):
            if isinstance(node.target, ast.Name) and node.target.id == name and node.value is not None:
                return node, [node.value]
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _MUTATORS
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == name
        ):
            return node, list(node.args)
        return None

    def _parameter(self, name: str, function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
        """Follow *name* to the callers of *function* in this file when it is a parameter."""
        args = function.args
        positional = [*args.posonlyargs, *args.args]
        index = next((at for at, arg in enumerate(positional) if arg.arg == name), None)
        variadic = args.vararg is not None and args.vararg.arg == name
        keyword = any(arg.arg == name for arg in args.kwonlyargs)
        if index is None and not variadic and not keyword:
            return False
        for call in ast.walk(self.tree):
            if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)):
                continue
            if call.func.id != function.name:
                continue
            caller = self.scope_of(call)
            for given in call.keywords:
                if given.arg == name:
                    self.trace(given.value, caller)
            if variadic:
                for given in call.args[len(positional):]:
                    self.trace(given, caller)
            elif index is not None and index < len(call.args):
                self.trace(call.args[index], caller)
        return True


def _module_arguments(tree: ast.Module) -> Iterator[tuple[ast.Call, ast.expr]]:
    """Every ``create_app(...)`` call of *tree*, with the expression that is its module list."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        called = node.func
        name = called.id if isinstance(called, ast.Name) else getattr(called, "attr", None)
        if name != "create_app":
            continue
        given = next((keyword.value for keyword in node.keywords if keyword.arg == "modules"), None)
        if given is None and node.args:
            given = node.args[0]
        if given is not None:
            yield node, given


def check_module_list_is_unconditional(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """The modules handed to ``create_app`` are not decided under a condition.

    A module mounted only where a setting is present is served there and nowhere else, so
    the access check (ADR 0209), which composes the app wherever it runs, records a surface
    the deployed app does not have. The rule follows the list back through the file: a
    conditional expression among its elements, an ``append`` under an ``if``, a filtering
    comprehension, a helper that returns it under a condition, and the same through a
    parameter to the function's callers in the file.
    """
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    for path in iter_python_files(root):
        tree = parse(path)
        calls = list(_module_arguments(tree))
        if not calls:
            continue
        file = _File(tree)
        for call, modules in calls:
            file.trace(modules, file.scope_of(call))
        violations.extend(
            ArchViolation(_RULE, _rel(path, root), line, message)
            for line, message in sorted(file.found.items())
        )
    return violations


__all__ = ["check_module_list_is_unconditional"]
