"""The schema half of the API-contract comparison (ADR 0194).

Two OpenAPI schemas are compared from the side of the client that depends on them: on a
request the new schema must accept everything the old one accepted, on a response it may
produce nothing the old one never did. References resolve within each document, a recursive
shape is compared once per pair of references, and a schema whose own text is unchanged is
still entered when a schema it reaches changed. :mod:`terp.cli.api_contract` walks the
operations and calls :func:`diff_schema` for each body, parameter and response.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any

#: Request-side bounds, each with the direction in which a change refuses what was accepted:
#: ``max`` bounds break when they fall (or appear), ``min`` bounds when they rise (or appear).
_UPPER_BOUNDS = ("maxLength", "maximum", "exclusiveMaximum", "maxItems")
_LOWER_BOUNDS = ("minLength", "minimum", "exclusiveMinimum", "minItems")

#: A recursion floor no real schema reaches, so a malformed document cannot hang the check.
_MAX_DEPTH = 64

REQUEST = "request"
RESPONSE = "response"


@dataclass(frozen=True, order=True)
class Change:
    """One difference between two contracts, phrased as the change a reviewer approves."""

    breaking: bool
    where: str
    what: str

    def render(self) -> str:
        return f"{'BREAKING ' if self.breaking else ''}{self.where}: {self.what}"


@dataclass(frozen=True)
class Docs:
    """The two documents a ``$ref`` on either side resolves against.

    *changed* is every component schema whose shape differs, directly or through a schema
    it refers to, so a node whose own text is unchanged is still entered when something it
    reaches changed.
    """

    before: Mapping[str, Any]
    after: Mapping[str, Any]
    changed: frozenset[str]


def schemas_of(document: Mapping[str, Any]) -> dict[str, Any]:
    return mapping(mapping(document.get("components")).get("schemas"))


def refs_in(node: Any) -> set[str]:
    """Every ``$ref`` written anywhere inside *node*, without following any of them."""
    if isinstance(node, Mapping):
        found = {node["$ref"]} if isinstance(node.get("$ref"), str) else set()
        for value in node.values():
            found |= refs_in(value)
        return found
    if isinstance(node, list):
        return set().union(*(refs_in(item) for item in node)) if node else set()
    return set()


def changed_refs(before: Mapping[str, Any], after: Mapping[str, Any]) -> frozenset[str]:
    old, new = schemas_of(before), schemas_of(after)
    names = old.keys() | new.keys()
    reference = {name: f"#/components/schemas/{name}" for name in names}
    changed = {reference[name] for name in names if old.get(name) != new.get(name)}
    depends = {reference[name]: refs_in(old.get(name)) | refs_in(new.get(name)) for name in names}
    grew = True
    while grew:
        grew = False
        for ref, needs in depends.items():
            if ref not in changed and needs & changed:
                changed.add(ref)
                grew = True
    return frozenset(changed)


def mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def resolve(node: Any, document: Mapping[str, Any]) -> dict[str, Any]:
    """Follow ``$ref`` within *document* until a node that is not a reference; ``{}`` if none."""
    seen: set[str] = set()
    current = mapping(node)
    while isinstance(current.get("$ref"), str):
        reference = current["$ref"]
        if reference in seen or not reference.startswith("#/"):
            return {}
        seen.add(reference)
        target: Any = document
        for part in reference[2:].split("/"):
            target = mapping(target).get(part.replace("~1", "/").replace("~0", "~"))
        current = mapping(target)
    return current


def _ref(node: Any) -> str | None:
    reference = mapping(node).get("$ref")
    return reference if isinstance(reference, str) else None


def _raw_members(schema: Mapping[str, Any]) -> list[Any]:
    """The alternatives a schema is a union of, as written; itself when it is no union."""
    for key in ("anyOf", "oneOf"):
        if isinstance(schema.get(key), list):
            return list(schema[key])
    return [dict(schema)]


def _members(schema: Mapping[str, Any], document: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The alternatives a schema is a union of, each resolved."""
    return [resolve(member, document) for member in _raw_members(schema)]


def _types(schema: Mapping[str, Any], document: Mapping[str, Any]) -> frozenset[str]:
    """The JSON types a schema admits; ``{"any"}`` when it says nothing about them."""
    found: set[str] = set()
    for member in _members(schema, document):
        declared = member.get("type")
        if isinstance(declared, str):
            found.add(declared)
        elif isinstance(declared, list):
            found.update(str(item) for item in declared)
        elif "const" in member:
            found.add(_json_type(member["const"]))
        elif isinstance(member.get("enum"), list):
            found.update(_json_type(value) for value in member["enum"])
        elif "properties" in member:
            found.add("object")
        elif "items" in member:
            found.add("array")
        else:
            found.add("any")
        if member.get("nullable") is True:
            found.add("null")
    return frozenset(found)


def _json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


def _admits(types: frozenset[str], kind: str) -> bool:
    return "any" in types or kind in types or (kind == "integer" and "number" in types)


def _enum(schema: Mapping[str, Any], document: Mapping[str, Any]) -> frozenset[str] | None:
    """Every value the schema's members enumerate, or ``None`` when one of them is open."""
    values: set[str] = set()
    for member in _members(schema, document):
        if member.get("type") == "null":
            continue
        if "const" in member:
            values.add(json.dumps(member["const"], sort_keys=True))
        elif isinstance(member.get("enum"), list):
            values.update(json.dumps(value, sort_keys=True) for value in member["enum"])
        else:
            return None
    return frozenset(values)


def _single(
    schema: Mapping[str, Any], document: Mapping[str, Any], kind: str
) -> tuple[str | None, dict[str, Any]] | None:
    """The one member of *kind* (``object`` or ``array``) a schema has, with its ``$ref``.

    ``None`` when there is no such member or more than one: a union of two object shapes
    is compared as a whole, by the fallback, rather than guessed at member by member.
    """
    found = []
    for raw in _raw_members(schema):
        member = resolve(raw, document)
        if kind in _types(member, document):
            found.append((_ref(raw), member))
    return found[0] if len(found) == 1 else None


def diff_schema(
    where: str,
    label: str,
    was: Any,
    now: Any,
    direction: str,
    docs: Docs,
    *,
    field: str = "",
    stack: tuple[tuple[str | None, str | None], ...] = (),
) -> Iterator[Change]:
    """Compare two schemas in *direction*; *field* is the dotted path inside the body."""
    pair = (_ref(was), _ref(now))
    if _seen(pair, stack):
        return
    stack = (*stack, pair)
    before = resolve(was, docs.before)
    after = resolve(now, docs.after)
    if before == after and pair[0] == pair[1] and not refs_in(before) & docs.changed:
        return
    subject = f"{label} field '{field}'" if field else label
    yield from _diff_value_set(where, subject, before, after, direction, docs)
    old_object = _single(before, docs.before, "object")
    new_object = _single(after, docs.after, "object")
    if old_object is not None and new_object is not None:
        # A member reached through a union is entered under its own reference, so a
        # recursive shape behind a nullable `anyOf` is compared once, not to the floor.
        member = (old_object[0], new_object[0])
        if not _seen(member, stack):
            yield from _diff_properties(
                where,
                label,
                old_object[1],
                new_object[1],
                direction,
                docs,
                field=field,
                stack=(*stack, member),
            )
    old_array = _single(before, docs.before, "array")
    new_array = _single(after, docs.after, "array")
    if old_array is not None and new_array is not None:
        yield from diff_schema(
            where,
            label,
            old_array[1].get("items"),
            new_array[1].get("items"),
            direction,
            docs,
            field=f"{field}[]" if field else "[]",
            stack=stack,
        )


def _seen(pair: tuple[str | None, str | None], stack: tuple[tuple[str | None, str | None], ...]) -> bool:
    """Whether comparing *pair* again would loop: a reference pair already on the way down."""
    return (pair != (None, None) and pair in stack) or len(stack) >= _MAX_DEPTH


def _diff_value_set(
    where: str,
    subject: str,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    direction: str,
    docs: Docs,
) -> Iterator[Change]:
    old_types = _types(before, docs.before)
    new_types = _types(after, docs.after)
    accepting, producing = (new_types, old_types) if direction == REQUEST else (old_types, new_types)
    escaped = ", ".join(
        "a value of any type" if kind == "any" else kind
        for kind in sorted(producing)
        if not _admits(accepting, kind)
    )
    if escaped:
        if direction == REQUEST:
            yield Change(True, where, f"{subject} no longer accepts {escaped}")
        else:
            yield Change(True, where, f"{subject} may now be {escaped}")
    elif old_types != new_types:
        yield Change(False, where, f"{subject} type {_spell(old_types)} -> {_spell(new_types)}")

    old_enum = _enum(before, docs.before)
    new_enum = _enum(after, docs.after)
    if old_enum != new_enum:
        if direction == REQUEST:
            narrowed = new_enum is not None and (old_enum is None or bool(old_enum - new_enum))
            if narrowed:
                lost = "values it accepted" if old_enum is None else ", ".join(sorted(old_enum - new_enum))  # type: ignore[operator]
                yield Change(True, where, f"{subject} no longer accepts {lost}")
            else:
                yield Change(False, where, f"{subject} accepts more values")
        else:
            widened = old_enum is not None and (new_enum is None or bool(new_enum - old_enum))
            if widened:
                gained = "any value" if new_enum is None else ", ".join(sorted(new_enum - old_enum))  # type: ignore[operator]
                yield Change(True, where, f"{subject} may now return {gained}")
            else:
                yield Change(False, where, f"{subject} returns fewer values")

    old_format = _format(before, docs.before)
    new_format = _format(after, docs.after)
    if old_format != new_format:
        tightened = new_format if direction == REQUEST else old_format
        if tightened is not None:
            yield Change(True, where, f"{subject} format {old_format or 'none'} -> {new_format or 'none'}")
        else:
            yield Change(False, where, f"{subject} format {old_format or 'none'} -> {new_format or 'none'}")

    if direction == REQUEST:
        yield from _diff_bounds(where, subject, _bounds(before, docs.before), _bounds(after, docs.after))


def _spell(types: frozenset[str]) -> str:
    return "|".join(sorted(types))


def _format(schema: Mapping[str, Any], document: Mapping[str, Any]) -> str | None:
    formats = {
        str(member["format"])
        for member in _members(schema, document)
        if isinstance(member.get("format"), str)
    }
    return ",".join(sorted(formats)) or None


def _bounds(schema: Mapping[str, Any], document: Mapping[str, Any]) -> dict[str, Any]:
    found: dict[str, Any] = {}
    for member in _members(schema, document):
        if member.get("type") == "null":
            continue
        for key in (*_UPPER_BOUNDS, *_LOWER_BOUNDS, "pattern"):
            if key in member:
                found[key] = member[key]
    return found


def _diff_bounds(where: str, subject: str, before: Mapping[str, Any], after: Mapping[str, Any]) -> Iterator[Change]:
    for key in _UPPER_BOUNDS:
        old, new = before.get(key), after.get(key)
        if old == new:
            continue
        if new is not None and (old is None or _number(new) < _number(old)):
            yield Change(True, where, f"{subject} {key} {old if old is not None else 'none'} -> {new}")
        else:
            yield Change(False, where, f"{subject} {key} {old} -> {new if new is not None else 'none'}")
    for key in _LOWER_BOUNDS:
        old, new = before.get(key), after.get(key)
        if old == new:
            continue
        if new is not None and (old is None or _number(new) > _number(old)):
            yield Change(True, where, f"{subject} {key} {old if old is not None else 'none'} -> {new}")
        else:
            yield Change(False, where, f"{subject} {key} {old} -> {new if new is not None else 'none'}")
    old_pattern, new_pattern = before.get("pattern"), after.get("pattern")
    if old_pattern != new_pattern:
        if new_pattern is not None:
            yield Change(True, where, f"{subject} must now match {new_pattern!r}")
        else:
            yield Change(False, where, f"{subject} no longer has to match {old_pattern!r}")


def _number(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def _diff_properties(
    where: str,
    label: str,
    was: Mapping[str, Any],
    now: Mapping[str, Any],
    direction: str,
    docs: Docs,
    *,
    field: str,
    stack: tuple[tuple[str | None, str | None], ...],
) -> Iterator[Change]:
    before = mapping(was.get("properties"))
    after = mapping(now.get("properties"))
    old_required = set(was.get("required") or ())
    new_required = set(now.get("required") or ())
    for name in sorted(before.keys() | after.keys()):
        path = f"{field}.{name}" if field else name
        subject = f"{label} field '{path}'"
        if name not in after:
            if direction == REQUEST:
                yield Change(True, where, f"{subject} removed - a client that sends it is refused or ignored")
            else:
                yield Change(True, where, f"{subject} removed")
            continue
        if name not in before:
            if direction == REQUEST and name in new_required:
                yield Change(True, where, f"{subject} is new and required")
            else:
                yield Change(False, where, f"new {subject}")
            continue
        if direction == REQUEST:
            if name in new_required and name not in old_required:
                yield Change(True, where, f"{subject} is now required")
            elif name in old_required and name not in new_required:
                yield Change(False, where, f"{subject} is now optional")
        else:
            if name in old_required and name not in new_required:
                yield Change(True, where, f"{subject} may now be absent")
            elif name in new_required and name not in old_required:
                yield Change(False, where, f"{subject} is now always present")
        yield from diff_schema(
            where, label, before[name], after[name], direction, docs, field=path, stack=stack
        )


__all__ = [
    "REQUEST",
    "RESPONSE",
    "Change",
    "Docs",
    "changed_refs",
    "diff_schema",
    "mapping",
    "refs_in",
    "resolve",
    "schemas_of",
]
