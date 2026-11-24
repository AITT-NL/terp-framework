"""One cycle in the graph of what modules require (``ModuleSpec.requires``).

Moved out of ``terp.core.app`` unchanged, beside which ``validate_requires`` still refuses a
cycle it finds: a pure walk of a graph, with nothing of the composition in it.
"""

from __future__ import annotations

from collections.abc import Mapping


def _find_requires_cycle(graph: Mapping[str, frozenset[str]]) -> list[str] | None:
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
