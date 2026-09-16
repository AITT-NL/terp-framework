"""File-size rule: no source file grows past the line-count cap.

A file that keeps growing stops being reviewable — it hides more than one
responsibility and is exactly what an automated author tends to produce when it
appends to an existing file instead of factoring the work into a new one. This
rule caps the physical line count of every scanned ``*.py`` file so a
responsibility that outgrows its file is split into its own file, not piled onto
the current one. Generated and machine-owned trees (dependency caches, the
database migration history, the test suite) are excluded by ``iter_python_files``
— their size is not an authoring decision the cap should second-guess.

The cap alone is a rule with no recipe: it names a number and leaves the author
to find the seam, which is the expensive half and the half the checker can
already see. So the violation also **proposes a cut**. The file's top-level
definitions form a graph — one definition references another — and the connected
components of that graph are the candidate groups. A candidate is only proposed
once it survives a second reading of the whole file: the graph knows nothing of
names bound by tuple unpacking or inside a top-level block, nor of references made
from module-level statements, and a group that reads one of those is not
independent however isolated the graph makes it look. Naming a group that passes
both turns "this file is too long" into "these definitions are already independent
of the rest; they are the file" — and naming none is the honest answer when no
group is.
"""

from __future__ import annotations

import ast
import pathlib
from collections.abc import Iterator

from terp.arch._ast import iter_python_files, parse
from terp.arch.rules._support import ArchViolation, _rel

#: Maximum number of physical lines a scanned source file may have. A file at or
#: below this stays reviewable in one sitting; past it, split cohesive helpers or
#: sub-services into their own modules.
_MAX_FILE_LINES = 500

#: How many names of a proposed seam to spell out before eliding the rest. Enough
#: to recognise the group; short enough that the message stays one readable line.
_SEAM_NAMES_SHOWN = 4


def _top_level_definitions(tree: ast.Module) -> dict[str, tuple[int, int]]:
    """Each top-level ``def`` / ``class`` / simple assignment, as ``name -> (start, end)``.

    Only definitions that own a span of lines are considered: those are the things
    that can be *moved*. Imports and bare statements stay where they are, and a
    name bound twice keeps its widest span so the estimate never under-counts.
    """
    spans: dict[str, tuple[int, int]] = {}

    def record(name: str, node: ast.stmt) -> None:
        end = getattr(node, "end_lineno", None) or node.lineno
        start, previous_end = spans.get(name, (node.lineno, end))
        spans[name] = (min(start, node.lineno), max(previous_end, end))

    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            record(node.name, node)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    record(target.id, node)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            record(node.target.id, node)
    return spans


def _referenced_names(node: ast.AST) -> set[str]:
    """Every bare name mentioned anywhere inside *node*."""
    return {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}


def _definition_components(tree: ast.Module) -> list[tuple[frozenset[str], int]]:
    """Connected groups of mutually-referencing top-level definitions, with line counts.

    Undirected on purpose: two definitions belong together whichever way the
    reference runs, because moving one without the other breaks the file either
    way. The result is sorted largest-group-first so the caller can propose the
    cut that buys the most.
    """
    spans = _top_level_definitions(tree)
    if not spans:
        return []
    parent = {name: name for name in spans}

    def find(name: str) -> str:
        while parent[name] != name:
            parent[name] = parent[parent[name]]
            name = parent[name]
        return name

    def union(left: str, right: str) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            owner = node.name
        elif isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            owner = targets[0] if targets else ""
            for extra in targets[1:]:
                union(owner, extra)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            owner = node.target.id
        else:
            continue
        if owner not in spans:
            continue
        for referenced in _referenced_names(node) & spans.keys():
            if referenced != owner:
                union(owner, referenced)

    grouped: dict[str, set[str]] = {}
    for name in spans:
        grouped.setdefault(find(name), set()).add(name)
    components = [
        (
            frozenset(members),
            sum(spans[member][1] - spans[member][0] + 1 for member in members),
        )
        for members in grouped.values()
    ]
    return sorted(components, key=lambda item: (-item[1], sorted(item[0])))


def _module_level_statements(tree: ast.Module) -> Iterator[ast.stmt]:
    """Every statement the module runs at import time, the ones inside blocks included.

    Recursion stops at a ``def`` / ``class``: their bodies bind locals and attributes,
    not module names. A top-level ``if`` / ``try`` / ``with`` / ``for`` is descended,
    because the names such a block binds are module names like any other — and they are
    exactly the ones a definition-only reading of the file cannot see.
    """
    pending = list(tree.body)
    while pending:
        node = pending.pop()
        yield node
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            continue
        for field in ("body", "orelse", "finalbody"):
            pending.extend(getattr(node, field, None) or [])
        for handler in getattr(node, "handlers", None) or []:
            pending.extend(handler.body)


def _module_level_bindings(tree: ast.Module) -> set[str]:
    """Every name the module binds, including the ones no cut can carry away.

    Deliberately wider than :func:`_top_level_definitions`, which answers "what could
    move". This answers "what does this file define at all", and the gap between the two
    is where the seam proposal used to go wrong: a name bound by tuple unpacking
    (``MIN_LEN, MAX_LEN = 1, 200``) or inside a top-level ``try`` / ``if TYPE_CHECKING``
    block is defined here and owns no span that could be lifted out. A group that reads
    one is not self-contained, however isolated its own references look.
    """
    bound: set[str] = set()
    for node in _module_level_statements(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            bound.add(node.name)
            continue
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign | ast.AugAssign):
            targets = [node.target]
        elif isinstance(node, ast.For | ast.AsyncFor):
            targets = [node.target]
        elif isinstance(node, ast.With | ast.AsyncWith):
            targets = [item.optional_vars for item in node.items if item.optional_vars]
        for target in targets:
            for inner in ast.walk(target):
                if isinstance(inner, ast.Name):
                    bound.add(inner.id)
    return bound


def _defines_movable(node: ast.stmt, movable: set[str]) -> bool:
    """True when *node* is one of the definitions the component graph already covers."""
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
        return node.name in movable
    if isinstance(node, ast.Assign):
        return any(
            isinstance(target, ast.Name) and target.id in movable
            for target in node.targets
        )
    if isinstance(node, ast.AnnAssign):
        return isinstance(node.target, ast.Name) and node.target.id in movable
    return False


def _pinned_by_residue(tree: ast.Module, movable: set[str]) -> set[str]:
    """Definitions named by module-level code that no cut can carry away.

    A registration call, a conditional re-export, a constant built from a class — these
    are statements rather than definitions, so they stay in the file whatever moves. A
    definition one of them names therefore cannot leave without the old module importing
    it back, and if the moved group also reads something anchored here, the two modules
    import each other. The component graph is built from definitions alone and cannot
    see any of that, which is why it is consulted rather than trusted.
    """
    pinned: set[str] = set()
    for node in _module_level_statements(tree):
        if _defines_movable(node, movable):
            continue
        for inner in ast.walk(node):
            if (
                isinstance(inner, ast.Name)
                and isinstance(inner.ctx, ast.Load)
                and inner.id in movable
            ):
                pinned.add(inner.id)
    return pinned


def _component_reads(tree: ast.Module, members: frozenset[str]) -> set[str]:
    """Every name the definitions in *members* mention."""
    read: set[str] = set()
    for node in tree.body:
        name = None
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            name = node.name
        elif isinstance(node, ast.Assign):
            name = next(
                (t.id for t in node.targets if isinstance(t, ast.Name)),
                None,
            )
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
        if name in members:
            read |= _referenced_names(node)
    return read


def _proposed_seam(path: pathlib.Path) -> str:
    """A sentence naming the largest liftable group of definitions, or ``""``.

    Silent when there is nothing honest to say — a file whose definitions all reference
    one another has no seam to propose, and inventing one would be worse than the bare
    cap, because an author who follows a bad suggestion ends up with two coupled files
    instead of one long one. That silence is the reason the candidate is checked against
    the whole file and not only against the definition graph: the graph is blind to
    names bound by tuple unpacking or inside a top-level block, and to references made
    from module-level statements, so a group can look perfectly isolated in it while
    reading a constant that stays behind. Proposing that cut produced the exact failure
    the docstring promises not to — two files importing each other.
    """
    try:
        tree = parse(path)
    except SyntaxError:
        return ""
    components = _definition_components(tree)
    if len(components) < 2:
        return ""
    movable = set(_top_level_definitions(tree))
    anchored = _module_level_bindings(tree) - movable
    pinned = _pinned_by_residue(tree, movable)
    for candidate, candidate_lines in components:
        if candidate & pinned:
            continue
        if _component_reads(tree, candidate) & anchored:
            continue
        members, lines = candidate, candidate_lines
        break
    else:
        return ""
    shown = sorted(members)
    listed = ", ".join(shown[:_SEAM_NAMES_SHOWN])
    if len(shown) > _SEAM_NAMES_SHOWN:
        listed += f", +{len(shown) - _SEAM_NAMES_SHOWN} more"
    return (
        f" The largest group of top-level definitions that nothing outside it "
        f"references is {listed} ({lines} lines across {len(shown)} definitions); "
        f"moving that group into its own module is a cut that leaves no dangling "
        f"name behind."
    )


def check_no_oversized_python_files(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """Every scanned ``*.py`` file stays at or under ``_MAX_FILE_LINES`` lines.

    Line count is physical (``str.splitlines``), so blank lines and comments count
    — the cap is about how much a reader has to scroll, not how much logic runs.
    Generated/vendored caches, the migration history and the test tree are excluded
    (``iter_python_files``); their size is not a hand-authored decision. A file past
    the cap is reported at line 1 so the opt-out marker lives naturally at the top.

    The message carries a proposed seam when the file has one (see
    :func:`_proposed_seam`), so the author is handed the cut rather than the number.
    """
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    for path in iter_python_files(root):
        count = len(path.read_text(encoding="utf-8").splitlines())
        if count <= _MAX_FILE_LINES:
            continue
        violations.append(
            ArchViolation(
                "no_oversized_python_files",
                _rel(path, root),
                1,
                f"file has {count} lines, over the {_MAX_FILE_LINES}-line cap; split it "
                "into smaller, cohesive modules (extract helpers or sub-services into "
                "their own files) so each stays reviewable in one sitting."
                + _proposed_seam(path),
            )
        )
    return violations


__all__ = ["check_no_oversized_python_files"]
