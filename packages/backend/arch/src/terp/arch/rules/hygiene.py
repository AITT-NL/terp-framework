"""Source-hygiene rules: cheap, unambiguous bans that keep app code honest.

A small family of build-time-only rules that each refuse one well-known
foot-gun in application source:

* ``no_eval_or_exec`` — dynamic code execution (a code-injection vector).
* ``no_star_imports`` — ``from x import *`` (hides the real dependency surface).
* ``no_blocking_sleep`` — ``time.sleep()`` (blocks the request/worker thread).
* ``no_print`` — ``print()`` (unstructured output; use logging).
* ``no_todo_fixme`` — TODO/FIXME/HACK/XXX placeholders (never resolved).
* ``no_mutable_default_args`` — a list/dict/set default shared across calls.
* ``no_empty_tests`` — a ``test_*`` function that asserts nothing.

Each invariant is a property of the authored source, so all seven are
build-time-only (``runtime.applicability: not-applicable`` in the catalog).
"""

from __future__ import annotations

import ast
import pathlib
import re

from terp.arch._ast import _SECURITY_SKIP_DIRS, base_name, iter_python_files, parse
from terp.arch.rules._support import ArchViolation, _file_comments, _rel

_PLACEHOLDER_RE = re.compile(r"\b(?:TODO|FIXME|HACK|XXX)\b", re.IGNORECASE)
_MUTABLE_DEFAULT_NODES = (ast.List, ast.Dict, ast.Set)


def check_no_eval_or_exec(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """``eval()`` and ``exec()`` are refused — dynamic code execution is a security risk.

    Both builtins run an arbitrary string as code, so any attacker-influenced input
    reaching one is a remote-code-execution hole. There is no safe in-app use: parse
    structured data, dispatch on a mapping, or import a real module instead. The scan
    covers tests and migrations too — importable Python that runs is in scope.
    """
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    for path in iter_python_files(root, skip_dirs=_SECURITY_SKIP_DIRS):
        tree = parse(path)
        rel = _rel(path, root)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in {"eval", "exec"}
            ):
                violations.append(
                    ArchViolation(
                        "no_eval_or_exec",
                        rel,
                        node.lineno,
                        f"{node.func.id}() runs a string as code (a code-injection "
                        "vector); parse the data or dispatch on a mapping instead",
                    )
                )
    return violations


def check_no_star_imports(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """``from x import *`` is refused — import the names you use explicitly.

    A wildcard import pulls an unknown, mutable set of names into the namespace, so
    the real dependency surface is invisible and a shadowed name is silent. Name each
    import so a reader (and the boundary rules) can see exactly what a module uses.
    """
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    for path in iter_python_files(root):
        tree = parse(path)
        rel = _rel(path, root)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and any(
                alias.name == "*" for alias in node.names
            ):
                module = node.module or "."
                violations.append(
                    ArchViolation(
                        "no_star_imports",
                        rel,
                        node.lineno,
                        f"'from {module} import *' hides the dependency surface; "
                        "import the names explicitly",
                    )
                )
    return violations


def check_no_blocking_sleep(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """``time.sleep()`` is refused — it blocks the request/worker thread.

    A synchronous sleep parks the thread serving the request (or the worker running
    the job), starving the pool. Poll with an awaitable, schedule a delayed job, or
    let the runtime back off — never freeze the thread.
    """
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    for path in iter_python_files(root):
        tree = parse(path)
        rel = _rel(path, root)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "sleep"
                and base_name(node.func.value) == "time"
            ):
                violations.append(
                    ArchViolation(
                        "no_blocking_sleep",
                        rel,
                        node.lineno,
                        "time.sleep() blocks the request/worker thread; use an "
                        "awaitable wait or a scheduled job instead",
                    )
                )
    return violations


def check_no_print(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """``print()`` is refused — emit through the structured logger instead.

    A bare print bypasses log levels, structure, and routing, so its output is
    invisible to the platform's logging pipeline and cannot be filtered or shipped.
    Call the logger so every diagnostic is levelled and captured.
    """
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    for path in iter_python_files(root):
        tree = parse(path)
        rel = _rel(path, root)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "print"
            ):
                violations.append(
                    ArchViolation(
                        "no_print",
                        rel,
                        node.lineno,
                        "print() bypasses the structured logger; use logging instead",
                    )
                )
    return violations


def check_no_todo_fixme(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """TODO/FIXME/HACK/XXX placeholder comments are refused — finish or drop the code.

    A placeholder marks unfinished work that ships anyway and is never revisited.
    Implement the missing behaviour, or delete the dead branch — do not leave a note
    promising a later fix. Matched only in real comment tokens, never in strings.
    """
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    for path in iter_python_files(root):
        rel = _rel(path, root)
        for lineno, comment in _file_comments(path.read_text(encoding="utf-8")):
            match = _PLACEHOLDER_RE.search(comment)
            if match:
                violations.append(
                    ArchViolation(
                        "no_todo_fixme",
                        rel,
                        lineno,
                        f"{match.group(0).upper()} placeholder comment; implement the "
                        "behaviour or remove the code — do not defer it in a comment",
                    )
                )
    return violations


def check_no_mutable_default_args(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """A mutable default argument (list/dict/set literal) is refused — use ``None``.

    A default value is evaluated once and shared across every call, so a mutable one
    accumulates state between calls — a classic aliasing bug. Default to ``None`` and
    build the container inside the body when the argument is omitted.
    """
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    for path in iter_python_files(root):
        tree = parse(path)
        rel = _rel(path, root)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            defaults = [d for d in node.args.defaults + node.args.kw_defaults if d is not None]
            if any(isinstance(default, _MUTABLE_DEFAULT_NODES) for default in defaults):
                violations.append(
                    ArchViolation(
                        "no_mutable_default_args",
                        rel,
                        node.lineno,
                        f"{node.name!r} has a mutable default argument shared across "
                        "calls; default to None and build the container in the body",
                    )
                )
    return violations


def _is_empty_test_body(body: list[ast.stmt]) -> str | None:
    """Return a reason string if *body* is a non-asserting test, else ``None``.

    Strips a leading docstring, then flags a body that is empty, a lone ``pass``,
    or a lone ``assert True`` / ``assert <truthy-constant>`` — none of which
    actually exercises anything.
    """
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    if not body:
        return "has an empty body"
    if len(body) == 1 and isinstance(body[0], ast.Pass):
        return "contains only `pass`"
    if len(body) == 1 and isinstance(body[0], ast.Assert):
        test = body[0].test
        if isinstance(test, ast.Constant) and bool(test.value):
            return "only asserts a constant truthy value — it can never fail"
    return None


def check_no_empty_tests(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """A ``test_*`` function must assert something — an empty or ``pass`` stub is refused.

    A test that only holds ``pass``, a docstring, or ``assert True`` passes
    unconditionally and gives false confidence. Every test must exercise real
    behaviour and assert a real outcome. Scans every ``test_*.py`` file (the test
    surface the other rules deliberately skip).
    """
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    for path in sorted(root.rglob("test_*.py")):
        if any(part in _SECURITY_SKIP_DIRS for part in path.parts):
            continue
        tree = parse(path)
        rel = _rel(path, root)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("test_"):
                continue
            reason = _is_empty_test_body(node.body)
            if reason is not None:
                violations.append(
                    ArchViolation(
                        "no_empty_tests",
                        rel,
                        node.lineno,
                        f"test {node.name!r} {reason}; assert a real outcome",
                    )
                )
    return violations


__all__ = [
    "check_no_blocking_sleep",
    "check_no_empty_tests",
    "check_no_eval_or_exec",
    "check_no_mutable_default_args",
    "check_no_print",
    "check_no_star_imports",
    "check_no_todo_fixme",
]
