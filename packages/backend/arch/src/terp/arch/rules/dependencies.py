"""Declared module dependency edges (ADR 0087).

A module may not reach for a sibling on a whim, but a real domain sometimes has a
real dependency — a catalog row that must name an existing connection, an intake
workflow that opens a ticket. Terp's answer is not "invert it by hand": it is to
make the edge **declared**, so it appears in the manifest a reader already
consults, and then check it.

``ModuleSpec.requires`` is that declaration. It already existed as a boot-time
presence check ("the thing you need is installed"); these rules give it its
second, larger meaning: **the exhaustive list of siblings this module may
import**. An undeclared sibling import stays refused by
``no_cross_module_imports``; a declared one is allowed, but only into the
dependency's public surface, and only if the resulting graph has no cycle.

The declaration is read from source, not by importing the app, so ``requires``
must be a literal tuple/list of string literals. That is a feature: a manifest a
static reader cannot understand is a manifest the next author cannot trust, and
an unreadable one grants nothing (fail closed).
"""

from __future__ import annotations

import ast
import pathlib

from terp.arch._ast import iter_python_files, parse
from terp.arch.rules._support import (
    ArchViolation,
    _imported_modules,
    _module_parts,
    _module_under,
    _rel,
)

# What a declared edge grants: the dependency's *domain vocabulary*, never its
# delivery surface. ``router`` is excluded on purpose — mounting or calling
# another module's routes couples two modules through HTTP shapes and would let a
# dependency's authorization policy be sidestepped by an in-process call. Anything
# underscore-prefixed is private by the same convention the rest of Terp uses.
PUBLIC_MODULE_SURFACE = frozenset({"models", "schemas", "service", "events"})


def _module_manifest_path(app_root: pathlib.Path, name: str) -> pathlib.Path:
    return app_root / "modules" / name / "module.py"


def _module_names(app_root: pathlib.Path) -> list[str]:
    """Every real ``modules/<name>/`` package under *app_root*.

    A directory counts as a module when it holds Python source, which keeps build
    artefacts (``__pycache__`` holds only ``.pyc``) and stray folders out of the
    graph. The test is deliberately looser than "has a manifest": a module whose
    manifest is missing or unreadable must stay *visible* as a module, so its
    dependants are told their edge is undeclared — the true fault — instead of
    the module silently ceasing to exist.
    """
    modules_dir = app_root / "modules"
    if not modules_dir.is_dir():
        return []
    return sorted(
        entry.name
        for entry in modules_dir.iterdir()
        if entry.is_dir() and any(entry.rglob("*.py"))
    )


def _literal_str_sequence(node: ast.expr) -> frozenset[str] | None:
    """The string literals in a literal tuple/list, or ``None`` if not static."""
    if not isinstance(node, ast.Tuple | ast.List):
        return None
    names: set[str] = set()
    for element in node.elts:
        if not isinstance(element, ast.Constant) or not isinstance(element.value, str):
            return None
        names.add(element.value)
    return frozenset(names)


def _declared_requires(app_root: pathlib.Path, name: str) -> frozenset[str]:
    """The sibling names *name* declares in its ``ModuleSpec(requires=...)``.

    Fails closed: a missing manifest, a manifest with no ``requires=``, or a
    ``requires=`` that is not a literal sequence of string literals all declare
    **nothing** — so every sibling import stays refused rather than being waved
    through by a declaration nobody can read.

    A manifest that does not *parse* is not handled here and does not need to be:
    it is an ordinary Python file, so the rule's own source scan has already
    raised on it. An unreadable-to-Python app fails the gate loudly, which is the
    fail-closed answer, rather than quietly becoming a module with no edges.
    """
    path = _module_manifest_path(app_root, name)
    if not path.exists():
        return frozenset()
    tree = parse(path)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        if called != "ModuleSpec":
            continue
        for keyword in node.keywords:
            if keyword.arg == "requires":
                return _literal_str_sequence(keyword.value) or frozenset()
    return frozenset()


def declared_dependency_graph(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> dict[str, frozenset[str]]:
    """Each module's declared sibling edges, restricted to modules that exist.

    A ``requires`` entry naming a capability (``"audit"``) rather than a sibling
    module is not an edge in this graph — it is the boot-time presence
    declaration, and the composition root already validates it.
    """
    root = pathlib.Path(app_root)
    names = _module_names(root)
    known = set(names)
    return {name: frozenset(_declared_requires(root, name) & known) for name in names}


def _find_cycle(graph: dict[str, frozenset[str]]) -> list[str] | None:
    """One cycle in *graph* as a node path (first node repeated last), or ``None``."""
    WHITE, GREY, BLACK = 0, 1, 2
    colour = dict.fromkeys(graph, WHITE)
    stack: list[str] = []

    def visit(node: str) -> list[str] | None:
        colour[node] = GREY
        stack.append(node)
        for target in sorted(graph.get(node, frozenset())):
            if colour.get(target, BLACK) == GREY:
                return [*stack[stack.index(target):], target]
            if colour.get(target, BLACK) == WHITE:
                found = visit(target)
                if found is not None:
                    return found
        colour[node] = BLACK
        stack.pop()
        return None

    for name in sorted(graph):
        if colour[name] == WHITE:
            found = visit(name)
            if found is not None:
                return found
    return None


def check_module_dependency_graph_is_acyclic(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """Declared module edges form a DAG — no module depends on itself, directly or not.

    A cycle is the point at which two "independent" modules have quietly become
    one: neither can be read, tested, deployed or removed without the other, and
    the direction that would tell you which owns the shared concept no longer
    exists. Terp refuses the cycle rather than the coupling, so the fix is the
    real one — extract the shared concept, or turn the weaker direction into an
    event subscription.
    """
    root = pathlib.Path(app_root)
    graph = declared_dependency_graph(root, package=package)
    cycle = _find_cycle(graph)
    if cycle is None:
        return []
    path = " -> ".join(cycle)
    return [
        ArchViolation(
            "module_dependency_graph_is_acyclic",
            _rel(_module_manifest_path(root, node), root),
            1,
            f"declared module dependencies form a cycle ({path}); module edges must "
            "be one-way — extract the shared concept into its own module, or invert "
            "the weaker direction into an event subscription",
        )
        for node in sorted(set(cycle))
    ]


def check_cross_module_imports_use_public_surface(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """A declared edge grants ``models`` / ``schemas`` / ``service`` / ``events`` only.

    The edge buys the dependency's domain vocabulary, not its delivery surface:
    importing another module's ``router`` couples two modules through HTTP shapes
    and lets an in-process call walk past the authorization policy that guards
    those routes, and importing a private (underscore-prefixed) submodule takes a
    dependency on something its owner never published.
    """
    root = pathlib.Path(app_root)
    prefix = f"{package}.modules."
    violations: list[ArchViolation] = []
    graph = declared_dependency_graph(root, package=package)
    for path in iter_python_files(root):
        own = _module_under(path, package)
        if own is None:
            continue
        allowed = graph.get(own, frozenset())
        tree = parse(path)
        rel = _rel(path, root)
        importing_parts = _module_parts(path, root)
        for module, line in _imported_modules(tree, importing_parts):
            if not module.startswith(prefix):
                continue
            tail = module[len(prefix):].split(".")
            target = tail[0]
            if target == own or target not in allowed:
                continue  # own module, or an undeclared edge the sibling rule reports
            surface = tail[1] if len(tail) > 1 else None
            if surface is None:
                violations.append(
                    ArchViolation(
                        "cross_module_imports_use_public_surface",
                        rel,
                        line,
                        f"module {own!r} imports the package {target!r} itself; import a "
                        f"named surface ({', '.join(sorted(PUBLIC_MODULE_SURFACE))}) so the "
                        "dependency is on a published shape, not on whatever that package "
                        "happens to re-export",
                    )
                )
            elif surface not in PUBLIC_MODULE_SURFACE:
                violations.append(
                    ArchViolation(
                        "cross_module_imports_use_public_surface",
                        rel,
                        line,
                        f"module {own!r} imports {target}.{surface!r}; a declared edge grants "
                        f"only {', '.join(sorted(PUBLIC_MODULE_SURFACE))} — never another "
                        "module's router or its private internals",
                    )
                )
    return violations
