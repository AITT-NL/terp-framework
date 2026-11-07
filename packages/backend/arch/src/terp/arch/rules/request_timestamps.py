"""Reading timestamp text without its UTC offset is an escape, named and counted (ADR 0206).

A ``BaseSchema`` refuses timestamp text that carries no UTC offset, and a declared filter
refuses a bound with none: such a value names no instant, and read as UTC it puts a writer in
another zone off by its offset. ``NaiveMeansUtc`` from ``terp.core`` is the framework's way
around both, for a sender known to send UTC without saying so, and this rule refuses each use
of it, so taking it is the rule's opt-out marker, which the app's escape-hatch budget counts.

An app's own validator that runs before a timestamp's type is the other way around (ADR 0207):
a ``before``, ``wrap`` or ``plain`` validator sees the text first, so it can read a wall time
in a zone of its choosing. A wall time in a named place is ``LocalTimeIn``'s, which names the
instant, so the rule counts such a validator on a timestamp field as the escape too. That half,
and the reading of types both halves share, is in :mod:`terp.arch.rules._timestamp_types`.
"""

from __future__ import annotations

import ast
import pathlib
from collections.abc import Iterator

from terp.arch._ast import base_name, iter_python_files, parse
from terp.arch.rules._support import ArchViolation, _rel
from terp.arch.rules._timestamp_types import _assignment, _early_validator_findings, _quoted_nodes

_NAIVE_MEANS_UTC = "NaiveMeansUtc"

#: The boundary's own machinery; an app takes the escape from ``terp.core``.
_TIMESTAMPS_MODULE = "terp.core.timestamps"

#: The packages the framework scans that implement the boundary rather than use it: the one
#: that defines the boundary and its escape, and the one that defines this rule, which names
#: both as the data it matches.
_IMPLEMENTING_PACKAGES = frozenset({"terp.core", "terp.arch"})

_ESCAPE_MESSAGE = (
    "NaiveMeansUtc reads a timestamp with no UTC offset as UTC, so a sender in any other "
    "zone is stored off by its offset; take the timestamp with its offset (a plain datetime "
    "field or filter refuses one without it), or, for a sender known to send UTC without "
    "saying so, keep it with '# arch-allow-request-timestamps-carry-their-offset: <reason>' "
    "(budgeted by the app's escape-hatch-budget.json)"
)
_MACHINERY_MESSAGE = (
    "terp.core.timestamps is the timestamp boundary's own module, which nothing outside the "
    "framework reaches; take the escape as NaiveMeansUtc from terp.core, where this rule "
    "counts each use, and recognise a refusal by its error type, timestamp_offset_required"
)


def _mentions(value: ast.expr, names: set[str]) -> bool:
    return any(
        (isinstance(inner, ast.Name) and inner.id in names)
        or (isinstance(inner, ast.Attribute) and inner.attr == _NAIVE_MEANS_UTC)
        for inner in [*ast.walk(value), *_quoted_nodes(value)]
    )


_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


def _bodies(scope: ast.AST) -> Iterator[ast.AST]:
    """The nodes of *scope* that run in it: not inside a nested function or class."""
    pending = list(ast.iter_child_nodes(scope))
    while pending:
        child = pending.pop()
        if not isinstance(child, _SCOPES):
            yield child
            pending.extend(ast.iter_child_nodes(child))


def _aliases_in(scope: ast.AST, visible: set[str]) -> set[str]:
    """The names *scope* binds to the escape, by import alias, assignment or type alias."""
    names = set(visible)
    for node in _bodies(scope):
        if isinstance(node, ast.ImportFrom):
            names.update(
                alias.asname for alias in node.names if alias.name == _NAIVE_MEANS_UTC and alias.asname
            )
    grown = True
    while grown:
        grown = False
        for node in _bodies(scope):
            targets, value = _assignment(node)
            if value is None or not _mentions(value, names):
                continue
            for target in targets:
                if target not in names:
                    names.add(target)
                    grown = True
    return names


def _nested_scopes(scope: ast.AST) -> Iterator[ast.AST]:
    """The functions, lambdas and classes nearest inside *scope*, not looking into them."""
    pending = list(ast.iter_child_nodes(scope))
    while pending:
        child = pending.pop()
        if isinstance(child, _SCOPES):
            yield child
        else:
            pending.extend(ast.iter_child_nodes(child))


def _locals(scope: ast.AST) -> set[str]:
    """The names a function binds for itself: its parameters and what it assigns."""
    bound: set[str] = set()
    if isinstance(scope, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
        arguments = scope.args
        for argument in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs):
            bound.add(argument.arg)
        for extra in (arguments.vararg, arguments.kwarg):
            if extra is not None:
                bound.add(extra.arg)
    for node in _bodies(scope):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            bound.add(node.id)
    return bound


def _core_aliases(tree: ast.Module) -> set[str]:
    """Dotted local names that mean the terp.core package in this file."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname is not None and alias.name == "terp.core":
                    found.add(alias.asname)
                elif alias.asname is None and alias.name.split(".")[0] == "terp":
                    found.add("terp.core")
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module == "terp":
            found.update(alias.asname or alias.name for alias in node.names if alias.name == "core")
    return found


def _dotted(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        head = _dotted(node.value)
        return None if head is None else f"{head}.{node.attr}"
    return None


def _names_machinery(name: str) -> bool:
    return name == _TIMESTAMPS_MODULE or name.startswith(f"{_TIMESTAMPS_MODULE}.")


def _imports_machinery(node: ast.AST) -> bool:
    """True for an import of the boundary's own module, or its dotted name as a literal.

    A literal is how ``importlib`` and ``sys.modules`` are handed the module.
    """
    if isinstance(node, ast.ImportFrom) and node.level == 0:
        if _names_machinery(node.module or ""):
            return True
        return node.module == "terp.core" and any(alias.name == "timestamps" for alias in node.names)
    if isinstance(node, ast.Import):
        return any(_names_machinery(alias.name) for alias in node.names)
    return isinstance(node, ast.Constant) and isinstance(node.value, str) and _names_machinery(node.value)


def _reaches_machinery(node: ast.AST, core: set[str]) -> bool:
    """True for ``timestamps`` taken from a name that means ``terp.core`` where it is read.

    As an attribute, or through ``getattr`` with that literal name.
    """
    if isinstance(node, ast.Attribute) and node.attr == "timestamps":
        return _dotted(node.value) in core
    if isinstance(node, ast.Call) and base_name(node.func) == "getattr" and len(node.args) >= 2:
        name = node.args[1]
        return isinstance(name, ast.Constant) and name.value == "timestamps" and _dotted(node.args[0]) in core
    return False


def _escape_findings(tree: ast.Module) -> dict[int, str]:
    """Each line that takes the escape, or reaches for its machinery, with its message.

    It fails closed by name: any reference to ``NaiveMeansUtc`` is the escape, whatever the
    file imported it from or shadows it with, and so is every name the file binds to it, at
    each use, where that binding is the one in scope, and every string that names one. A class
    attribute bound to it counts at each use of that attribute's name, through the class, a
    subclass or an instance.
    """
    findings: dict[int, str] = {}
    module_aliases = _aliases_in(tree, {_NAIVE_MEANS_UTC})
    core = _core_aliases(tree)

    def escape(node: ast.AST) -> None:
        findings.setdefault(getattr(node, "lineno", 0), _ESCAPE_MESSAGE)

    def machinery(node: ast.AST) -> None:
        findings[getattr(node, "lineno", 0)] = _MACHINERY_MESSAGE

    attribute_aliases: set[str] = set()

    def judge(scope: ast.AST, visible: set[str], core_visible: set[str]) -> None:
        """Flag the scope's own uses of what it sees, then each scope nested in it."""
        for node in _bodies(scope):
            if (
                isinstance(node, ast.Name)
                and isinstance(node.ctx, ast.Load)
                and (node.id == _NAIVE_MEANS_UTC or node.id in visible)
            ):
                escape(node)
            elif _reaches_machinery(node, core_visible):
                machinery(node)
        for nested in _nested_scopes(scope):
            if isinstance(nested, ast.ClassDef):
                class_aliases = _aliases_in(nested, visible)
                attribute_aliases.update(class_aliases - visible)
                judge(nested, class_aliases, core_visible)
            else:
                own = _locals(nested)
                judge(
                    nested,
                    _aliases_in(nested, {name for name in visible if name not in own}),
                    {name for name in core_visible if name.split(".")[0] not in own},
                )

    judge(tree, module_aliases, core)

    quoted = _quoted_nodes(tree)
    for node in [*ast.walk(tree), *quoted]:
        if isinstance(node, ast.Attribute) and (
            node.attr == _NAIVE_MEANS_UTC or node.attr in attribute_aliases
        ):
            escape(node)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id == _NAIVE_MEANS_UTC:
            escape(node)
        elif (
            isinstance(node, ast.Call)
            and base_name(node.func) == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value == _NAIVE_MEANS_UTC
        ):
            escape(node)
        elif _imports_machinery(node):
            machinery(node)
        elif isinstance(node, ast.ImportFrom) and any(
            alias.name == _NAIVE_MEANS_UTC and alias.asname not in (None, _NAIVE_MEANS_UTC)
            for alias in node.names
        ):
            escape(node)
    for node in quoted:
        if isinstance(node, ast.Name) and node.id in module_aliases:
            escape(node)
        elif _reaches_machinery(node, core):
            machinery(node)
    return findings


def check_request_timestamps_carry_their_offset(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """Reading timestamp text without its UTC offset is an escape, named and counted.

    A ``BaseSchema`` refuses timestamp text that carries no UTC offset, and a declared filter
    refuses a bound with none (ADR 0206): such a value names no instant, and read as UTC it
    puts a writer in another zone off by its offset. ``NaiveMeansUtc`` is the framework's way
    around both, for a sender known to send UTC without saying so. Each use of it is refused
    here, so taking it is this rule's opt-out marker, which the app's escape-hatch budget
    counts. The rule fails closed by name: every reference to ``NaiveMeansUtc``, or to a name
    the file binds to it, and every string that names one, is the escape, and so is reaching
    for the boundary's own module. So is an app's own ``before``, ``wrap`` or ``plain``
    validator on a timestamp field (ADR 0207), which reads the text before the type does: a
    wall time in a named zone is ``LocalTimeIn``'s, which names the instant.
    """
    if package in _IMPLEMENTING_PACKAGES:
        return []  # the boundary's own implementation, and this rule's, is neither's user
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    for path in iter_python_files(root):
        tree = parse(path)
        rel = _rel(path, root)
        findings = _escape_findings(tree)
        for line, message in _early_validator_findings(tree).items():
            findings.setdefault(line, message)
        violations.extend(
            ArchViolation("request_timestamps_carry_their_offset", rel, line, message)
            for line, message in sorted(findings.items())
        )
    return violations


__all__ = ["check_request_timestamps_carry_their_offset"]
