"""Phase 1 gate (static): the ``terp.core`` layer-0 boundary keystone.

This AST check is the **build-time** layer of the Phase 1 gate; the runtime
layer is that ``terp.core`` actually ships only ``terp.core`` + stdlib /
third-party imports and constructs cleanly. Neither layer may be weakened to
make a change pass.
"""

from __future__ import annotations

import ast
import pathlib

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CORE_SRC = _REPO_ROOT / "packages" / "backend" / "core" / "src" / "terp" / "core"


def _core_py_files() -> list[pathlib.Path]:
    return sorted(_CORE_SRC.rglob("*.py"))


def _module_name(path: pathlib.Path) -> str:
    relative = path.relative_to(_CORE_SRC.parent).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(["terp", *parts])


def _resolve_import_from(path: pathlib.Path, node: ast.ImportFrom) -> str | None:
    if node.level == 0:
        return node.module
    current = _module_name(path).split(".")
    if path.name != "__init__.py":
        current.pop()
    keep = len(current) - node.level + 1
    if keep < 0:
        return None
    parts = current[:keep]
    if node.module:
        parts.extend(node.module.split("."))
    return ".".join(parts)


def _imported_modules(path: pathlib.Path, tree: ast.Module) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = _resolve_import_from(path, node)
            if module:
                modules.add(module)
    return modules


def test_core_source_present() -> None:
    """Sanity: the scan actually has files to check (guards against false greens)."""
    files = {p.name for p in _core_py_files()}
    assert {"__init__.py", "base_models.py", "errors.py", "module_spec.py"} <= files


def test_core_imports_nothing_above() -> None:
    """Keystone: ``terp.core`` (layer 0) imports only ``terp.core`` + stdlib/3rd-party."""
    violations: list[str] = []
    for path in _core_py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for module in _imported_modules(path, tree):
            top = module.split(".")[0]
            if top == "terp" and not (module == "terp.core" or module.startswith("terp.core.")):
                violations.append(f"{path.relative_to(_REPO_ROOT)}: imports {module!r}")
            elif top == "app":
                violations.append(f"{path.relative_to(_REPO_ROOT)}: imports app code {module!r}")

    assert not violations, (
        "terp.core must import nothing above layer 0 (no terp.capabilities / "
        "terp.arch / app.*):\n" + "\n".join(f"  - {v}" for v in violations)
    )


def test_relative_imports_are_resolved_before_boundary_check() -> None:
    """A relative import cannot spell an above-core dependency to evade the gate."""
    path = _CORE_SRC / "nested" / "module.py"
    tree = ast.parse("from ...capabilities.users import spec\nfrom .local import helper\n")

    modules = _imported_modules(path, tree)

    assert "terp.capabilities.users" in modules
    assert "terp.core.nested.local" in modules
