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

_ESCAPE_MESSAGE = (
    "NaiveMeansUtc reads a timestamp with no UTC offset as UTC, so a sender in any other "
    "zone is stored off by its offset; take the timestamp with its offset (a plain datetime "
    "field or filter refuses one without it), or, for a sender known to send UTC without "
    "saying so, keep it with '# arch-allow-request-timestamps-carry-their-offset: <reason>' "
    "(budgeted by the app's escape-hatch-budget.json)"
)
_MACHINERY_MESSAGE = (
    "terp.core.timestamps is the boundary's own machinery, which nothing outside the "
    "framework imports; take the escape as NaiveMeansUtc from terp.core, where this rule "
    "counts each use"
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
    type_alias = getattr(ast, "TypeAlias", None)
    if type_alias is not None and isinstance(node, type_alias):
        return [node.name.id], node.value
    return [], None


def _escape_names(tree: ast.Module) -> set[str]:
    """The escape's name and every name this file binds to it: by import, assignment, alias."""
    names = {_NAIVE_MEANS_UTC}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names.update(
                alias.asname for alias in node.names if alias.name == _NAIVE_MEANS_UTC and alias.asname
            )
    grown = True
    while grown:
        grown = False
        for node in ast.walk(tree):
            targets, value = _assignment(node)
            if value is None or not any(
                (isinstance(inner, ast.Name) and inner.id in names)
                or (isinstance(inner, ast.Attribute) and inner.attr == _NAIVE_MEANS_UTC)
                for inner in ast.walk(value)
            ):
                continue
            for target in targets:
                if target not in names:
                    names.add(target)
                    grown = True
    return names


def _escape_findings(tree: ast.Module) -> dict[int, str]:
    """Each line that takes the escape, or reaches for its machinery, with its message.

    It fails closed by name: any reference to ``NaiveMeansUtc``, or to a name the file binds
    to it, is the escape, whatever the file imported it from.
    """
    names = _escape_names(tree)
    findings: dict[int, str] = {}

    def escape(node: ast.AST) -> None:
        findings.setdefault(getattr(node, "lineno", 0), _ESCAPE_MESSAGE)

    for node in [*ast.walk(tree), *_quoted_annotation_nodes(tree)]:
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in names:
            escape(node)
        elif isinstance(node, ast.Attribute) and node.attr == _NAIVE_MEANS_UTC:
            escape(node)
        elif (
            isinstance(node, ast.Call)
            and base_name(node.func) == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value == _NAIVE_MEANS_UTC
        ):
            escape(node)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module == _TIMESTAMPS_MODULE:
                findings[node.lineno] = _MACHINERY_MESSAGE
            elif any(
                alias.name == _NAIVE_MEANS_UTC and alias.asname not in (None, _NAIVE_MEANS_UTC)
                for alias in node.names
            ):
                escape(node)
        elif isinstance(node, ast.Import) and any(
            alias.name == _TIMESTAMPS_MODULE or alias.name.startswith(f"{_TIMESTAMPS_MODULE}.")
            for alias in node.names
        ):
            findings[node.lineno] = _MACHINERY_MESSAGE
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
