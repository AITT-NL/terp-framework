"""The schema half of the API-contract comparison (ADR 0194).

Two OpenAPI schemas are compared from the side of the client that depends on them: on a
request the new schema must accept everything the old one accepted, on a response it may
produce nothing the old one never did. References resolve within each document, a recursive
shape is compared once per pair of references, and a schema whose own text is unchanged is
still entered when a schema it reaches changed. :mod:`terp.cli.api_contract` walks the
operations and calls :func:`diff_schema` for each body, parameter and response.

What the rules at a node do not read (a default, ``additionalProperties``, ``allOf``, the
members of a union of object shapes, and whatever lies behind a reference inside them) is
compared too, with every reference resolved. A difference there is a line of its own that
names the node and counts as breaking, whatever the node's other rules or its fields found.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from typing import Any

from terp.cli.api_contract_bounds import LOWER_BOUNDS, UPPER_BOUNDS, diff_bounds
from terp.cli.api_contract_shapes import (
    EDITORIAL,
    SCHEMA_REF,
    Change,
    Docs,
    canonical_text,
    follow,
    mapping,
    ref_of,
    refs_in,
    resolve,
    same,
    shape,
    unclassified,
)

#: A recursion floor no real schema reaches, so a malformed document cannot hang the check.
_MAX_DEPTH = 64

REQUEST = "request"
RESPONSE = "response"

#: What the value-set rules read of every alternative: the kind of value it is.
_TYPE_KEYS = frozenset({"type", "nullable"})

#: What they read of a schema's one alternative beside ``null``, which they compare as its
#: own. Of a union of several values they read these as one pooled set, which loses which
#: alternative a bound or a format belonged to, so there they are left for :func:`_unread`.
_VALUE_KEYS = frozenset({"format", "const", "enum", "pattern", *UPPER_BOUNDS, *LOWER_BOUNDS})


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


def _missing(wide: frozenset[str] | None, narrow: frozenset[str] | None, *, everything: str) -> str | None:
    """What *narrow* no longer allows of *wide*, or ``None``: an open set (``None``) drops
    nothing when it is the target, and *everything* when it is the source."""
    if narrow is None:
        return None
    if wide is None:
        return everything
    dropped = wide - narrow
    return ", ".join(sorted(dropped)) if dropped else None


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


def _of_kind(
    schema: Mapping[str, Any], document: Mapping[str, Any], kind: str
) -> list[tuple[int, str | None, dict[str, Any]]]:
    """Every member of *kind* (``object`` or ``array``) a schema has: its place, ``$ref`` and body.

    Only a schema with exactly one on each side has it compared field by field: a union of
    two object shapes is compared as a whole, by :func:`_unread`, rather than guessed at
    member by member.
    """
    found = []
    for index, raw in enumerate(_raw_members(schema)):
        member = resolve(raw, document)
        if kind in _types(member, document):
            found.append((index, ref_of(raw), member))
    return found


def _read_at(mine: list[tuple[int, str | None, dict[str, Any]]], theirs: list[Any]) -> int | None:
    """The member whose fields (or items) the walk compares on this side, if it compares any:
    only when each side has exactly one."""
    return mine[0][0] if len(mine) == 1 and len(theirs) == 1 else None


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
    if canonical_text(shape(was)) == canonical_text(shape(now)) and _settled(refs_in(was) | refs_in(now), docs):
        return
    subject = f"{label} field '{field}'" if field else label
    pair = (ref_of(was), ref_of(now))
    if pair[0] is not None and pair[0] == pair[1]:
        docs.covered.add(pair[0])
    if _cycle(pair, stack):
        # An ancestor compares this pair of references, so only what is written beside
        # them is this node's own.
        if not same(follow(was, docs.before)[1], follow(now, docs.after)[1], docs):
            docs.cover(was, now)
            yield unclassified(where, subject)
        return
    if len(stack) >= _MAX_DEPTH or not all(node is None or isinstance(node, Mapping) for node in (was, now)):
        # Deeper than any real schema, or no schema object at all: nothing reads it.
        docs.cover(was, now)
        yield unclassified(where, subject)
        return
    stack = (*stack, pair)
    before = resolve(was, docs.before)
    after = resolve(now, docs.after)
    found = list(_diff_value_set(where, subject, before, after, direction, docs))
    old_objects, new_objects = _of_kind(before, docs.before, "object"), _of_kind(after, docs.after, "object")
    if len(old_objects) == 1 and len(new_objects) == 1:
        (_, old_ref, old_member), (_, new_ref, new_member) = old_objects[0], new_objects[0]
        # A member reached through a union is entered under its own reference, so a
        # recursive shape behind a nullable `anyOf` is compared once, not to the floor.
        member = (old_ref, new_ref)
        if old_ref is not None and old_ref == new_ref:
            docs.covered.add(old_ref)
        if not _cycle(member, stack):
            found.extend(
                _diff_properties(
                    where, label, old_member, new_member, direction, docs, field=field, stack=(*stack, member)
                )
            )
    old_arrays, new_arrays = _of_kind(before, docs.before, "array"), _of_kind(after, docs.after, "array")
    if len(old_arrays) == 1 and len(new_arrays) == 1:
        found.extend(
            diff_schema(
                where,
                label,
                old_arrays[0][2].get("items"),
                new_arrays[0][2].get("items"),
                direction,
                docs,
                field=f"{field}[]" if field else "[]",
                stack=stack,
            )
        )
    # What none of that read is compared on its own, whatever the rules above or the
    # fields below found, so a run never reports "0 breaking" over a change this check
    # cannot read: a default, `additionalProperties`, `allOf`, a union of object shapes,
    # and whatever is behind a reference inside them.
    several = len(_valued(before, docs.before)) > 1 and len(_valued(after, docs.after)) > 1
    old_unread = _unread(
        was, before, docs.before, objects=_read_at(old_objects, new_objects),
        arrays=_read_at(old_arrays, new_arrays), union=several,
    )
    new_unread = _unread(
        now, after, docs.after, objects=_read_at(new_objects, old_objects),
        arrays=_read_at(new_arrays, old_arrays), union=several,
    )
    if not same(old_unread, new_unread, docs):
        docs.cover(was, now, old_unread, new_unread)
        found.append(unclassified(where, subject))
    yield from found


def _cycle(pair: tuple[str | None, str | None], stack: tuple[tuple[str | None, str | None], ...]) -> bool:
    """Whether comparing *pair* again would loop: a pair of references already on the way down.

    Both halves have to be references. A schema written out in place is finite, so a pair
    with one is a new comparison, never a loop, and the depth floor bounds what is left.
    """
    return None not in pair and pair in stack


def _settled(references: set[str], docs: Docs) -> bool:
    """Whether nothing *references* reach can differ: each names a component schema, and
    none of those changed, directly or through one it refers to."""
    for reference in references:
        parts = reference.split("/")
        if len(parts) < 4 or "/".join(parts[:3]) + "/" != SCHEMA_REF or "/".join(parts[:4]) in docs.changed:
            return False
    return True


def _valued(schema: Mapping[str, Any], document: Mapping[str, Any]) -> list[int]:
    """Where a schema's alternatives that are not ``null`` sit among its members."""
    return [index for index, member in enumerate(_members(schema, document)) if member.get("type") != "null"]


def _unread(
    written: Any,
    schema: Mapping[str, Any],
    document: Mapping[str, Any],
    *,
    objects: int | None,
    arrays: int | None,
    union: bool,
) -> dict[str, Any]:
    """What of *schema* the rules at this node leave unread, for :func:`same` to compare.

    What is said of the schema's one value beside ``null`` is compared wherever it is written:
    beside its reference, on the union around it, or on the value itself, so a default that
    moves when a field stops being nullable is no difference. Of that value the value-set rules
    read the type, format, enum and bounds, and the walk the fields or items that *objects* or
    *arrays* name. Any other alternative keeps everything but its fields or items, with its
    type, so a bound or a format moving from one alternative to another is still a difference;
    one that is only a type (``null``, a plain ``string``) is read in full. *union* is whether
    the union keyword is read, which it is only when both sides are unions of several values:
    ``anyOf`` and ``oneOf`` agree on a value and ``null``.
    """
    members = _raw_members(schema)
    resolved = [resolve(member, document) for member in members]
    valued = [index for index, member in enumerate(resolved) if member.get("type") != "null"]
    single = valued[0] if len(valued) == 1 else None
    keyword = next((key for key in ("anyOf", "oneOf") if isinstance(schema.get(key), list)), None)
    said = follow(written, document)[1]
    if keyword is not None:
        said.append({key: value for key, value in schema.items() if key != keyword and key not in EDITORIAL})
    others: list[list[dict[str, Any]]] = []
    for index, (raw, member) in enumerate(zip(members, resolved, strict=True)):
        if not isinstance(raw, Mapping):
            others.append([{"$written": raw}])  # a boolean schema: no rule reads one
            continue
        read = _TYPE_KEYS | EDITORIAL | (_VALUE_KEYS if index == single else frozenset())
        if index == objects:
            read |= {"properties", "required"}
        if index == arrays:
            read |= {"items"}
        rest = [{key: value for key, value in member.items() if key not in read}, *follow(raw, document)[1]]
        if index == objects:
            # A required name with no property of its own is not one the fields compare.
            names = member.get("required")
            listed = mapping(member.get("properties"))
            unlisted = [name for name in names if name not in listed] if isinstance(names, list) else names
            if unlisted:
                rest.append({"required": unlisted})
        if index == single:
            said.extend(rest)
        elif any(rest):
            others.append(_entries(*rest, {key: member[key] for key in _TYPE_KEYS if key in member}))
    unread: dict[str, Any] = {"said": _entries(*said), "members": others}
    if union:
        unread["union"] = keyword
    return unread


def _entries(*sources: Mapping[str, Any]) -> list[dict[str, Any]]:
    """What *sources* say, one key to an entry in the order of the keys: where each was
    written is no difference."""
    entries = [{key: value} for source in sources for key, value in source.items()]
    return sorted(entries, key=lambda entry: next(iter(entry)))


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
            lost = _missing(old_enum, new_enum, everything="values it accepted")
            if lost is not None:
                yield Change(True, where, f"{subject} no longer accepts {lost}")
            else:
                yield Change(False, where, f"{subject} accepts more values")
        else:
            gained = _missing(new_enum, old_enum, everything="any value")
            if gained is not None:
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

    old_bounds, new_bounds = _bounds(before, docs.before), _bounds(after, docs.after)
    if direction == REQUEST:
        yield from diff_bounds(where, subject, old_bounds, new_bounds)
    else:
        # A response bound constrains what the server sends, so moving it never fails a
        # reader that was built on the old one; it is named, and never breaking.
        for key in sorted(old_bounds.keys() | new_bounds.keys()):
            if old_bounds.get(key) != new_bounds.get(key):
                yield Change(False, where, f"{subject} {key} {old_bounds.get(key, 'none')} -> {new_bounds.get(key, 'none')}")


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
        for key in (*UPPER_BOUNDS, *LOWER_BOUNDS, "pattern"):
            if key in member:
                found[key] = member[key]
    return found


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


__all__ = ["REQUEST", "RESPONSE", "diff_schema"]
