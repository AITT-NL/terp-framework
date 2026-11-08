"""The request-side bounds of a schema, compared from the side of the client that sends them.

A bound that tightens refuses a value a sender built on the old shape could send, so it is
breaking; one that loosens is not. ``terp.cli.api_contract_schemas`` walks the schemas and
hands each pair's bounds here (ADR 0194).
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

from terp.cli.api_contract_shapes import Change

#: Request-side bounds, each with the direction in which a change refuses what was accepted:
#: ``max`` bounds break when they fall (or appear), ``min`` bounds when they rise (or appear).
UPPER_BOUNDS = ("maxLength", "maximum", "exclusiveMaximum", "maxItems")
LOWER_BOUNDS = ("minLength", "minimum", "exclusiveMinimum", "minItems")

#: The bounds OpenAPI 3.0 writes as a boolean beside ``maximum`` or ``minimum``.
_EXCLUSIVE = frozenset({"exclusiveMaximum", "exclusiveMinimum"})


def _admits_the_bound(key: str, value: Any) -> bool:
    """Whether *value* of *key* refuses nothing: no exclusive bound, or 3.0's ``false``."""
    return key in _EXCLUSIVE and (value is None or value is False)


def diff_bounds(where: str, subject: str, before: Mapping[str, Any], after: Mapping[str, Any]) -> Iterator[Change]:
    for key in UPPER_BOUNDS:
        old, new = before.get(key), after.get(key)
        if _same_value(old, new):
            continue
        if _admits_the_bound(key, old) and _admits_the_bound(key, new):
            # 3.0's ``false`` admits exactly what absence admits: the text changed, not the shape.
            yield Change(False, where, f"{subject} {key} {_shown(old)} -> {_shown(new)}")
            continue
        if _excludes(old, new):
            yield Change(True, where, f"{subject} {key} {old if old is not None else 'none'} -> {new}")
        elif new is not None and (old is None or _number(new) < _number(old)):
            yield Change(True, where, f"{subject} {key} {old if old is not None else 'none'} -> {new}")
        else:
            yield Change(False, where, f"{subject} {key} {old} -> {new if new is not None else 'none'}")
    for key in LOWER_BOUNDS:
        old, new = before.get(key), after.get(key)
        if _same_value(old, new):
            continue
        if _admits_the_bound(key, old) and _admits_the_bound(key, new):
            yield Change(False, where, f"{subject} {key} {_shown(old)} -> {_shown(new)}")
            continue
        if _excludes(old, new):
            yield Change(True, where, f"{subject} {key} {old if old is not None else 'none'} -> {new}")
        elif new is not None and (old is None or _number(new) > _number(old)):
            yield Change(True, where, f"{subject} {key} {old if old is not None else 'none'} -> {new}")
        else:
            yield Change(False, where, f"{subject} {key} {old} -> {new if new is not None else 'none'}")
    old_pattern, new_pattern = before.get("pattern"), after.get("pattern")
    if old_pattern != new_pattern:
        if new_pattern is not None:
            yield Change(True, where, f"{subject} must now match {new_pattern!r}")
        else:
            yield Change(False, where, f"{subject} no longer has to match {old_pattern!r}")


def _shown(value: Any) -> str:
    return "none" if value is None else str(value)


def _number(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def _same_value(old: Any, new: Any) -> bool:
    """One bound value, as the file writes it: ``1`` and ``true`` are two values here too."""
    return type(old) is type(new) and old == new


def _excludes(old: Any, new: Any) -> bool:
    """Whether an OpenAPI 3.0 boolean ``exclusive*`` bound now shuts the bound's own value out.

    3.0 writes ``exclusiveMaximum: true`` beside ``maximum``, so the bound itself is refused;
    ``false`` or absence admits it. Turning it on refuses a value the sender could send, and
    is a tightening whatever the bound's number did. 3.1 writes the number itself, which the
    numeric comparison reads.
    """
    return new is True and old is not True


__all__ = ["LOWER_BOUNDS", "UPPER_BOUNDS", "diff_bounds"]
