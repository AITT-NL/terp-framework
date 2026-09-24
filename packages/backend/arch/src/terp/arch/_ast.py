"""AST + filesystem helpers for the Terp architecture harness (internal).

Pure, side-effect-free scanning utilities shared by the rules in
:mod:`terp.arch.rules`. Nothing here imports an app's domain code — the harness
is a static analyser, so it runs in well under a second and can gate every push.
"""

from __future__ import annotations

import ast
import contextlib
import pathlib
from collections.abc import Iterator
from contextvars import ContextVar

# Directory names that never contain enforceable application surface. ``tests``
# is skipped because test code legitimately constructs sessions/engines and
# fixtures that the runtime rules forbid in app code.
_SKIP_DIRS = frozenset({"__pycache__", "tests", ".venv", "node_modules", "migrations"})

# The skip set for *security* rules: ``tests`` and ``migrations`` are still
# importable Python, so credentials, dynamic SQL, and raw egress hidden there
# would otherwise dodge every scan while running at import time. Security rules
# therefore skip only the dirs that genuinely hold no application code.
_SECURITY_SKIP_DIRS = frozenset({"__pycache__", ".venv", "node_modules"})


#: The per-run memo, or ``None`` outside a run. Two maps: parsed modules by path, and
#: file listings by ``(root, skip_dirs)``.
_RUN_CACHE: ContextVar[tuple[dict, dict] | None] = ContextVar("terp_arch_scan", default=None)


@contextlib.contextmanager
def scan_cache() -> Iterator[None]:
    """Memoise reads and parses for the duration of one scan.

    The harness runs every rule over the same tree, and each rule walks and parses it
    independently: on a 32-file tree that is 2,354 ``ast.parse`` calls for 32 files, and
    the redundancy is the RULE COUNT, which only goes up. Nothing in ``rules`` mutates a
    tree -- every rule reads via ``ast.walk`` -- so one parse per file per run is the
    same analysis at a fraction of the work.

    Scoped to a run rather than cached on the module, and that is the whole design. A
    process-global cache keyed on the path would answer from a stale tree the moment
    anything rewrote a file between scans, which is exactly what this repository's own
    rule tests do (write ``main.py``, check, rewrite it, check again) and what an editor
    or a workbench does continuously. Keying on ``st_mtime_ns`` would paper over most of
    that and still lose to two writes inside one timestamp tick. A run-scoped memo has no
    such window: the filesystem cannot change under a scan that has already started, and
    outside a run ``parse`` and ``iter_python_files`` behave exactly as they always did --
    so a caller holding one of these functions directly, as the tests do, is unaffected.

    Re-entrant by design: a nested ``with`` shares the outer run's memo rather than
    starting an empty one, so a rule that composes another rule pays nothing extra.
    """
    if _RUN_CACHE.get() is not None:
        yield
        return
    token = _RUN_CACHE.set(({}, {}))
    try:
        yield
    finally:
        _RUN_CACHE.reset(token)


def iter_python_files(
    root: pathlib.Path, *, skip_dirs: frozenset[str] = _SKIP_DIRS
) -> Iterator[pathlib.Path]:
    """Yield every ``*.py`` file under *root*, skipping dirs named in *skip_dirs*.

    The walk itself is memoised inside :func:`scan_cache`, for the same reason the parse
    is: every rule re-walks the same tree. Returns a fresh iterator each call, so a
    caller that exhausts it does not empty it for the next one.
    """
    cache = _RUN_CACHE.get()
    if cache is None:
        return iter(_walk(root, skip_dirs))
    listings = cache[1]
    key = (root, skip_dirs)
    files = listings.get(key)
    if files is None:
        files = _walk(root, skip_dirs)
        listings[key] = files
    return iter(files)


def _walk(root: pathlib.Path, skip_dirs: frozenset[str]) -> tuple[pathlib.Path, ...]:
    return tuple(
        path
        for path in sorted(root.rglob("*.py"))
        if not any(part in skip_dirs for part in path.parts)
    )


def parse(path: pathlib.Path) -> ast.Module:
    """Parse *path* into an AST module.

    Inside :func:`scan_cache` the module is parsed once per run and the SAME tree is
    handed to every later caller. That is sound only because no rule mutates one; if a
    rule ever needs to, it must copy first.
    """
    cache = _RUN_CACHE.get()
    if cache is None:
        return ast.parse(path.read_text(encoding="utf-8"))
    trees = cache[0]
    tree = trees.get(path)
    if tree is None:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        trees[path] = tree
    return tree


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


__all__ = [
    "_SECURITY_SKIP_DIRS",
    "base_name",
    "iter_imports",
    "iter_python_files",
    "parse",
    "scan_cache",
]
