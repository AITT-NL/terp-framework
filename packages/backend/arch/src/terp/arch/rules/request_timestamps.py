"""Reading timestamp text without its UTC offset is an escape, named and counted (ADR 0206).

A ``BaseSchema`` refuses timestamp text that carries no UTC offset, and a declared filter
refuses a bound with none: such a value names no instant, and read as UTC it puts a writer in
another zone off by its offset. ``NaiveMeansUtc`` from ``terp.core`` is the framework's way
around both, for a sender known to send UTC without saying so, and this rule refuses each use
of it, so taking it is the rule's opt-out marker, which the app's escape-hatch budget counts.
"""

from __future__ import annotations

import ast
import pathlib
from collections.abc import Iterator

from terp.arch._ast import base_name, iter_python_files, parse
from terp.arch.rules._support import ArchViolation, _rel
from terp.arch.rules.datetimes import _bound_names

_NAIVE_MEANS_UTC = "NaiveMeansUtc"

#: The boundary's own machinery; an app takes the escape from ``terp.core``.
_TIMESTAMPS_MODULE = "terp.core.timestamps"

#: The package that defines the boundary and the escape, which the framework scans as one.
_ESCAPE_PACKAGE = "terp.core"

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


def _strings_outside_literals(expr: ast.AST) -> Iterator[ast.Constant]:
    if isinstance(expr, ast.Subscript) and base_name(expr.value) == "Literal":
        return
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        yield expr
        return
    for child in ast.iter_child_nodes(expr):
        yield from _strings_outside_literals(child)


def _annotations(tree: ast.Module) -> list[ast.expr]:
    """Every annotation in *tree*: of an assignment, a parameter, and a return."""
    found: list[ast.expr] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign):
            found.append(node.annotation)
        elif isinstance(node, ast.arg) and node.annotation is not None:
            found.append(node.annotation)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.returns is not None:
            found.append(node.returns)
    return found


def _quoted_annotation_nodes(tree: ast.Module) -> list[ast.AST]:
    """The nodes of every quoted annotation, parsed, with the quote's line.

    A quoted annotation (``"NaiveMeansUtc | None"``) is evaluated all the same, so it takes
    the escape as surely as an unquoted one. A ``Literal`` value is text, not an annotation.
    """
    found: list[ast.AST] = []
    for annotation in _annotations(tree):
        for quote in _strings_outside_literals(annotation):
            try:
                parsed = ast.parse(quote.value, mode="eval")
            except SyntaxError:
                continue
            for node in ast.walk(parsed):
                if isinstance(node, ast.expr):
                    ast.copy_location(node, quote)
                found.append(node)
    return found


def _assignment(node: ast.AST) -> tuple[list[str], ast.expr | None]:
    if isinstance(node, ast.Assign):
        return [name for target in node.targets for name in _bound_names(target)], node.value
    if isinstance(node, ast.AnnAssign) and node.value is not None:
        return _bound_names(node.target), node.value
    if isinstance(node, ast.TypeAlias) and isinstance(node.name, ast.Name):
        return [node.name.id], node.value
    return [], None


def _mentions(value: ast.expr, names: set[str]) -> bool:
    return any(
        (isinstance(inner, ast.Name) and inner.id in names)
        or (isinstance(inner, ast.Attribute) and inner.attr == _NAIVE_MEANS_UTC)
        for inner in ast.walk(value)
    )


def _bodies(scope: ast.AST) -> Iterator[ast.AST]:
    """The nodes of *scope* that run in it: not inside a nested function or class."""
    for child in ast.iter_child_nodes(scope):
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda | ast.ClassDef):
            continue
        yield child
        yield from _bodies(child)


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
    for child in ast.iter_child_nodes(scope):
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda | ast.ClassDef):
            yield child
        else:
            yield from _nested_scopes(child)


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


def _reaches_machinery(node: ast.AST, core: set[str]) -> bool:
    """True for whatever reaches the boundary's own module.

    An import of it, an attribute or a literal ``getattr`` of ``timestamps`` on a name the file
    binds to ``terp.core``, and its dotted name written as a literal, which is how
    ``importlib`` and ``sys.modules`` are handed it.
    """
    if isinstance(node, ast.ImportFrom) and node.level == 0:
        if _names_machinery(node.module or ""):
            return True
        return node.module == "terp.core" and any(alias.name == "timestamps" for alias in node.names)
    if isinstance(node, ast.Import):
        return any(_names_machinery(alias.name) for alias in node.names)
    if isinstance(node, ast.Attribute) and node.attr == "timestamps":
        return _dotted(node.value) in core
    if isinstance(node, ast.Call) and base_name(node.func) == "getattr" and len(node.args) >= 2:
        name = node.args[1]
        return isinstance(name, ast.Constant) and name.value == "timestamps" and _dotted(node.args[0]) in core
    return isinstance(node, ast.Constant) and isinstance(node.value, str) and _names_machinery(node.value)


def _escape_findings(tree: ast.Module) -> dict[int, str]:
    """Each line that takes the escape, or reaches for its machinery, with its message.

    It fails closed by name: any reference to ``NaiveMeansUtc`` is the escape, whatever the
    file imported it from or shadows it with, and so is every name the file binds to it, at
    each use, where that binding is the one in scope. A class attribute bound to it counts at
    each use through the class.
    """
    findings: dict[int, str] = {}
    module_aliases = _aliases_in(tree, {_NAIVE_MEANS_UTC})
    core = _core_aliases(tree)

    def escape(node: ast.AST) -> None:
        findings.setdefault(getattr(node, "lineno", 0), _ESCAPE_MESSAGE)

    attribute_aliases: set[tuple[str, str]] = set()

    def judge(scope: ast.AST, visible: set[str]) -> None:
        """Flag the scope's own uses of what it sees, then each scope nested in it."""
        for node in _bodies(scope):
            if (
                isinstance(node, ast.Name)
                and isinstance(node.ctx, ast.Load)
                and (node.id == _NAIVE_MEANS_UTC or node.id in visible)
            ):
                escape(node)
        for nested in _nested_scopes(scope):
            if isinstance(nested, ast.ClassDef):
                class_aliases = _aliases_in(nested, visible)
                attribute_aliases.update((nested.name, alias) for alias in class_aliases - visible)
                judge(nested, class_aliases)
            else:
                own = _locals(nested)
                judge(nested, _aliases_in(nested, {name for name in visible if name not in own}))

    judge(tree, module_aliases)

    for node in [*ast.walk(tree), *_quoted_annotation_nodes(tree)]:
        if isinstance(node, ast.Attribute) and (
            node.attr == _NAIVE_MEANS_UTC
            or (isinstance(node.value, ast.Name) and (node.value.id, node.attr) in attribute_aliases)
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
        elif _reaches_machinery(node, core):
            findings[getattr(node, "lineno", 0)] = _MACHINERY_MESSAGE
        elif isinstance(node, ast.ImportFrom) and any(
            alias.name == _NAIVE_MEANS_UTC and alias.asname not in (None, _NAIVE_MEANS_UTC)
            for alias in node.names
        ):
            escape(node)
    for node in _quoted_annotation_nodes(tree):
        if isinstance(node, ast.Name) and node.id in module_aliases:
            escape(node)
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
    the file binds to it, is the escape, and so is reaching for the boundary's own module.
    """
    if package == _ESCAPE_PACKAGE:
        return []  # the package that defines the boundary and its escape is neither's user
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    for path in iter_python_files(root):
        tree = parse(path)
        rel = _rel(path, root)
        findings = _escape_findings(tree)
        violations.extend(
            ArchViolation("request_timestamps_carry_their_offset", rel, line, message)
            for line, message in sorted(findings.items())
        )
    return violations


__all__ = ["check_request_timestamps_carry_their_offset"]
