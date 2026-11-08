"""Which early validators, and types that carry one, each file takes from the app's other modules.

``request_timestamps_carry_their_offset`` counts an app's own early validator on a timestamp
where it is declared, and at each use of a type that carries one, as each use of
``NaiveMeansUtc`` counts (ADR 0207). A check reads one file at a time, so a type declared in
one module and used in another was counted once, where it was declared: one marker covered
every field of every module that imported it. This pass reads the app's modules together and
binds, for each file, the names it imports from the others to what they are, by name or as a
module's attribute, following a re-export until nothing new is bound.
"""

from __future__ import annotations

import ast
import pathlib
from collections.abc import Sequence

from terp.arch.rules._support import _resolve_relative_import
from terp.arch.rules._timestamp_types import Imported, early_names


def _parts(path: pathlib.Path, app_root: pathlib.Path) -> list[str]:
    """*path*'s dotted parts from the app package's parent, ``__init__`` kept, so a relative
    import in a package's ``__init__`` resolves against the package itself."""
    return list(path.relative_to(app_root.parent).with_suffix("").parts)


def _taken(
    tree: ast.Module, parts: list[str], instances: frozenset[str], carriers: frozenset[str]
) -> Imported:
    """What *tree* imports of the qualified *instances* and *carriers*, and the modules it binds."""
    modules: dict[str, str] = {}
    taken_instances: set[str] = set()
    taken_carriers: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                head = alias.name.split(".")[0]
                modules[alias.asname or head] = alias.name if alias.asname else head
        elif isinstance(node, ast.ImportFrom):
            source = (
                node.module or ""
                if node.level == 0
                else _resolve_relative_import(parts, node.level, node.module)
            )
            for alias in node.names:
                local, qualified = alias.asname or alias.name, f"{source}.{alias.name}"
                modules[local] = qualified
                if qualified in instances:
                    taken_instances.add(local)
                if qualified in carriers:
                    taken_carriers.add(local)
    return Imported(frozenset(taken_instances), frozenset(taken_carriers), modules, instances, carriers)


def imports_of_early_validators(
    files: Sequence[tuple[pathlib.Path, ast.Module]], app_root: pathlib.Path
) -> dict[pathlib.Path, Imported]:
    """For each of *files*, the early validators and carrying types it imports from the others."""
    parts = {path: _parts(path, app_root) for path, _ in files}
    instances: frozenset[str] = frozenset()
    carriers: frozenset[str] = frozenset()
    imported: dict[pathlib.Path, Imported] = {}
    grown = True
    while grown:
        grown = False
        for path, tree in files:
            imported[path] = _taken(tree, parts[path], instances, carriers)
            own = parts[path][:-1] if parts[path][-1] == "__init__" else parts[path]
            module = ".".join(own)
            names_i, names_c = early_names(tree, imported[path])
            fresh_i = {f"{module}.{name}" for name in names_i} - instances
            fresh_c = {f"{module}.{name}" for name in names_c} - carriers
            if fresh_i or fresh_c:
                instances, carriers = instances | fresh_i, carriers | fresh_c
                grown = True
    return imported


__all__ = ["imports_of_early_validators"]
