"""Optimistic-concurrency rules: the version token is owned by the persistence layer.

Every row carries an integer concurrency token that the persistence layer bumps
on each UPDATE and checks against the value the client loaded. Writing that token
by hand does not raise — it silently overwrites the loaded value, so the
concurrency check compares a row against itself and a lost update slips through.
These rules keep the token out of application hands.
"""

from __future__ import annotations

import ast
import pathlib
from collections.abc import Iterable

from terp.arch._ast import base_name, iter_python_files, parse
from terp.arch.rules._support import ArchViolation, _rel

_VERSION_ATTR = "version"
_UPDATE_BASE = "BaseUpdateSchema"



def _assigns_version_attribute(target: ast.expr) -> bool:
    """True when *target* is an attribute assignment to ``.version`` (``x.version``)."""
    return isinstance(target, ast.Attribute) and target.attr == _VERSION_ATTR


def _is_setattr_version(node: ast.Call) -> bool:
    """True for ``setattr(obj, "version", ...)`` — the dynamic spelling of the same write."""
    if not (isinstance(node.func, ast.Name) and node.func.id == "setattr"):
        return False
    return (
        len(node.args) >= 2
        and isinstance(node.args[1], ast.Constant)
        and node.args[1].value == _VERSION_ATTR
    )


def check_no_manual_version_assignment(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """The optimistic-concurrency token is never assigned by hand.

    Assigning ``<row>.version`` (or ``setattr(<row>, "version", ...)``) overwrites the
    value the caller loaded, which is exactly what the concurrency check compares
    against — so a hand-written token silently disables lost-update detection instead
    of failing loudly. The persistence layer owns the token: it bumps and checks it on
    every UPDATE, so application code must leave it untouched.
    """
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    for path in iter_python_files(root):
        tree = parse(path)
        rel = _rel(path, root)
        for node in ast.walk(tree):
            targets: list[ast.expr] = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, ast.AugAssign | ast.AnnAssign):
                targets = [node.target]
            elif isinstance(node, ast.Call) and _is_setattr_version(node):
                violations.append(
                    ArchViolation(
                        "no_manual_version_assignment",
                        rel,
                        node.lineno,
                        "the optimistic-concurrency token is set by hand via setattr; the "
                        "persistence layer owns it — remove the write so the loaded value "
                        "survives for the concurrency check",
                    )
                )
                continue
            for target in targets:
                if _assigns_version_attribute(target):
                    violations.append(
                        ArchViolation(
                            "no_manual_version_assignment",
                            rel,
                            node.lineno,
                            "the optimistic-concurrency token is assigned by hand; this "
                            "overwrites the loaded value and silently disables lost-update "
                            "detection — remove the assignment, the update seam bumps it",
                        )
                    )
    return violations


def _update_schema_wiring(trees: Iterable[ast.AST]) -> set[str]:
    """Names of classes wired as an update body via ``build_crud_router(update_schema=...)``."""
    names: set[str] = set()
    for tree in trees:
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and base_name(node.func) == "build_crud_router":
                names.update(
                    keyword.value.id
                    for keyword in node.keywords
                    if keyword.arg == "update_schema" and isinstance(keyword.value, ast.Name)
                )
    return names


def _inherits_update_base(name: str, bases_by_class: dict[str, set[str]]) -> bool:
    """True when *name* reaches ``BaseUpdateSchema`` by following base edges in scope."""
    seen: set[str] = set()
    frontier = [name]
    while frontier:
        current = frontier.pop()
        if current in seen:
            continue
        seen.add(current)
        parents = bases_by_class.get(current, set())
        if _UPDATE_BASE in parents:
            return True
        frontier.extend(parents)
    return False


def check_update_schemas_inherit_base_update_schema(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """Every update DTO opts into optimistic concurrency by inheriting the update base.

    The update base carries the concurrency token as a required field, so a client
    must echo the version it loaded and the update seam can reject a stale write. An
    update DTO that does not inherit it is missing that required field — the token is
    never demanded, and a blind overwrite (a lost update) goes through. An update DTO
    is a class named ``*Update`` or one wired as a CRUD router's update body; each must
    reach the update base through its bases. (The token itself is never redeclared on
    the DTO — that is a framework-managed column the input-column rule already refuses;
    the field arrives by inheritance.)
    """
    root = pathlib.Path(app_root)
    parsed = [(_rel(path, root), parse(path)) for path in iter_python_files(root)]
    trees = [tree for _, tree in parsed]
    wired = _update_schema_wiring(trees)
    bases_by_class: dict[str, set[str]] = {}
    for tree in trees:
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                bases_by_class[node.name] = {base_name(base) for base in node.bases}

    violations: list[ArchViolation] = []
    for rel, tree in parsed:
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if node.name == _UPDATE_BASE:
                continue
            is_update_dto = node.name.endswith("Update") or node.name in wired
            if not is_update_dto:
                continue
            if _inherits_update_base(node.name, bases_by_class):
                continue
            violations.append(
                ArchViolation(
                    "update_schemas_inherit_base_update_schema",
                    rel,
                    node.lineno,
                    f"{node.name}: update DTO does not inherit the optimistic-concurrency "
                    "update base, so it never requires the version token a client must echo "
                    "— inherit it so a stale write is rejected instead of silently winning",
                )
            )
    return violations


__all__ = [
    "check_no_manual_version_assignment",
    "check_update_schemas_inherit_base_update_schema",
]