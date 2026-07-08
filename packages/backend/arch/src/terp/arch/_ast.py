"""AST + filesystem helpers for the Terp architecture harness (internal).

Pure, side-effect-free scanning utilities shared by the rules in
:mod:`terp.arch.rules`. Nothing here imports an app's domain code — the harness
is a static analyser, so it runs in well under a second and can gate every push.
"""

from __future__ import annotations

import ast
import pathlib
from collections.abc import Iterator

# Directory names that never contain enforceable application surface. ``tests``
# is skipped because test code legitimately constructs sessions/engines and
# fixtures that the runtime rules forbid in app code.
_SKIP_DIRS = frozenset({"__pycache__", "tests", ".venv", "node_modules", "migrations"})

# The skip set for *security* rules: ``tests`` and ``migrations`` are still
# importable Python, so credentials, dynamic SQL, and raw egress hidden there
# would otherwise dodge every scan while running at import time. Security rules
# therefore skip only the dirs that genuinely hold no application code.
_SECURITY_SKIP_DIRS = frozenset({"__pycache__", ".venv", "node_modules"})


def iter_python_files(
    root: pathlib.Path, *, skip_dirs: frozenset[str] = _SKIP_DIRS
) -> Iterator[pathlib.Path]:
    """Yield every ``*.py`` file under *root*, skipping dirs named in *skip_dirs*."""
    for path in sorted(root.rglob("*.py")):
        if any(part in skip_dirs for part in path.parts):
            continue
        yield path


def parse(path: pathlib.Path) -> ast.Module:
    """Parse *path* into an AST module."""
    return ast.parse(path.read_text(encoding="utf-8"))


def iter_imports(tree: ast.Module) -> Iterator[tuple[str, int]]:
    """Yield ``(absolute_module, lineno)`` for every absolute import in *tree*."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, node.lineno
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.module, node.lineno


def base_name(node: ast.expr) -> str | None:
    """Return the simple name of a base / decorator / annotation expression.

    Unwraps attribute access (``a.b.C`` → ``"C"``) and subscripts
    (``BaseService[X]`` → ``"BaseService"``) so callers can match on the leaf
    identifier without importing anything.
    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        return base_name(node.value)
    if isinstance(node, ast.Call):
        return base_name(node.func)
    return None


__all__ = ["_SECURITY_SKIP_DIRS", "base_name", "iter_imports", "iter_python_files", "parse"]
