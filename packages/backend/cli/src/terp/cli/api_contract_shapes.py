"""What both halves of the API-contract comparison share (ADR 0194).

A line (:class:`Change`), the two documents a reference resolves in (:class:`Docs`), and two
ways of comparing nodes. :func:`shape` reads what is written, without the editorial keys and
without the order of lists whose order nothing reads. :func:`same` reads what is meant, every
``$ref`` resolved within its own document, so a schema renamed behind a reference is the same
and a change behind one is not.

:mod:`terp.cli.api_contract` walks the operations and :mod:`terp.cli.api_contract_schemas`
the schemas. At every place either one compares, what no rule there reads is compared with
:func:`same`, and a difference in it is a line of its own that counts as breaking, whatever
else that place or the rest of the document produced.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

#: Keys that describe a document without changing any shape a client depends on.
EDITORIAL = frozenset(
    {"description", "summary", "title", "tags", "operationId", "examples", "example", "externalDocs"}
)

#: Keys whose value maps names to definitions. The names are data, so a property called
#: ``title`` is never mistaken for the editorial keyword of the same spelling.
_NAMED_MAPS = frozenset(
    {"properties", "patternProperties", "$defs", "definitions", "schemas", "paths", "responses",
     "content", "securitySchemes", "headers", "parameters", "requestBodies"}
)

#: Lists whose order carries no meaning for a client.
_ORDER_FREE = frozenset({"required", "enum", "type"})

#: How a component schema is referred to, and the key :attr:`Docs.depends` uses for it.
SCHEMA_REF = "#/components/schemas/"


@dataclass(frozen=True, order=True)
class Change:
    """One difference between two contracts, phrased as the change a reviewer approves."""

    breaking: bool
    where: str
    what: str

    def render(self) -> str:
        return f"{'BREAKING ' if self.breaking else ''}{self.where}: {self.what}"


@dataclass(frozen=True, eq=False)
class Docs:
    """The two documents a ``$ref`` on either side resolves against.

    *changed* is every component schema whose shape differs, directly or through a schema it
    refers to, so a node whose own text is unchanged is still entered when something it reaches
    changed. *depends* is what each component schema refers to. *covered* fills as the walk
    goes: every component schema compared with itself, or behind a line, so one that changed
    and is in neither is still named (:func:`terp.cli.api_contract.diff_contract`).
    """

    before: Mapping[str, Any]
    after: Mapping[str, Any]
    changed: frozenset[str]
    depends: Mapping[str, frozenset[str]] = field(default_factory=dict)
    covered: set[str] = field(default_factory=set)

    @classmethod
    def of(cls, before: Mapping[str, Any], after: Mapping[str, Any]) -> Docs:
        old, new = schemas_of(before), schemas_of(after)
        names = old.keys() | new.keys()
        depends = {
            SCHEMA_REF + name: frozenset(refs_in(old.get(name)) | refs_in(new.get(name))) for name in names
        }
        changed = {
            SCHEMA_REF + name
            for name in names
            if canonical_text(shape(old.get(name))) != canonical_text(shape(new.get(name)))
        }
        grew = True
        while grew:
            grew = False
            for ref, needs in depends.items():
                if ref not in changed and needs & changed:
                    changed.add(ref)
                    grew = True
        return cls(before, after, frozenset(changed), depends)

    def cover(self, *nodes: Any) -> None:
        """Account for every component schema *nodes* reach: a line naming them stands for it."""
        pending = set().union(*(refs_in(node) for node in nodes))
        while pending:
            ref = pending.pop()
            if ref not in self.covered:
                self.covered.add(ref)
                pending |= self.depends.get(ref, frozenset()) - self.covered


def shape(node: Any, *, names: bool = False) -> Any:
    """*node* as a client depends on it: no editorial keys, order-free lists sorted.

    Two nodes with equal shapes differ only in text or in an order nothing reads, so a
    difference that survives this is one a reviewer has to look at.
    """
    if isinstance(node, Mapping):
        if names:
            return {key: shape(value) for key, value in node.items()}
        found: dict[str, Any] = {}
        for key, value in node.items():
            if key in EDITORIAL:
                continue
            if key in _ORDER_FREE and isinstance(value, list):
                found[key] = _order_free(value)
            else:
                found[key] = shape(value, names=key in _NAMED_MAPS)
        return found
    if isinstance(node, list):
        return [shape(item) for item in node]
    return node


def _order_free(values: list[Any]) -> list[str]:
    return sorted(json.dumps(item, sort_keys=True) for item in values)


def canonical_text(node: Any) -> str:
    """*node* as the text a contract file carries, so ``true``, ``1`` and ``1.0`` are three values.

    Python reads those three as equal, and a comparison that trusts ``==`` would call a
    boolean field that became an integer "no change" while ``terp openapi`` writes a different
    file. The file's own text is the pin, so equality is decided on it.
    """
    return json.dumps(node, sort_keys=True, separators=(",", ":"))


def unclassified(where: str, subject: str) -> Change:
    """The line for a difference no rule classifies: counted as breaking until reviewed."""
    return Change(
        True, where, f"{subject} changed in a way this check does not classify - review it as breaking"
    )


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


def mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def ref_of(node: Any) -> str | None:
    """The ``$ref`` *node* is, or ``None`` when it is not a reference."""
    reference = mapping(node).get("$ref")
    return reference if isinstance(reference, str) else None


def _pointer(reference: str, document: Mapping[str, Any]) -> Any:
    target: Any = document
    for part in reference[2:].split("/"):
        target = mapping(target).get(part.replace("~1", "/").replace("~0", "~"))
    return target


def follow(node: Any, document: Mapping[str, Any]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """The node *node* refers to, and what is written beside each ``$ref`` on the way there.

    OpenAPI 3.1 lets a reference carry keys of its own, and a generator writes a field's
    ``default`` there, so they are part of what the node says. The node is ``None`` when the
    reference resolves nowhere: it dangles, points outside the document, or loops.
    """
    beside: list[dict[str, Any]] = []
    seen: set[str] = set()
    current: Any = node
    while (reference := ref_of(current)) is not None:
        written = {key: value for key, value in mapping(current).items() if key != "$ref" and key not in EDITORIAL}
        if written:
            beside.append(written)
        if reference in seen or not reference.startswith("#/"):
            return None, beside
        seen.add(reference)
        current = _pointer(reference, document)
        if not isinstance(current, Mapping):
            return None, beside
    return mapping(current), beside


def resolve(node: Any, document: Mapping[str, Any]) -> dict[str, Any]:
    """Follow ``$ref`` within *document* until a node that is not a reference; ``{}`` if none."""
    target, _ = follow(node, document)
    return target if target is not None else {}


def same(before: Any, after: Any, docs: Docs) -> bool:
    """Whether two nodes mean one shape, every ``$ref`` resolved within its own document.

    A recursive shape is compared once per pair of nodes: a pair already being compared is
    taken as equal, which is sound because a difference inside it is found where that pair
    is compared, and any difference ends the whole comparison.
    """
    return _same(before, after, docs, set(), names=False)


def _same(before: Any, after: Any, docs: Docs, pending: set[tuple[object, object]], *, names: bool) -> bool:
    if isinstance(before, Mapping) and isinstance(after, Mapping):
        if not names and (ref_of(before) is not None or ref_of(after) is not None):
            return _same_reference(before, after, docs, pending)
        keys = {key for key in before if names or key not in EDITORIAL}
        if keys != {key for key in after if names or key not in EDITORIAL}:
            return False
        for key in keys:
            was, now = before[key], after[key]
            if not names and key in _ORDER_FREE and isinstance(was, list) and isinstance(now, list):
                if _order_free(was) != _order_free(now):
                    return False
            elif not _same(was, now, docs, pending, names=not names and key in _NAMED_MAPS):
                return False
        return True
    if isinstance(before, list) and isinstance(after, list):
        return len(before) == len(after) and all(
            _same(was, now, docs, pending, names=False) for was, now in zip(before, after, strict=True)
        )
    return type(before) is type(after) and before == after


def _same_reference(
    before: Mapping[str, Any], after: Mapping[str, Any], docs: Docs, pending: set[tuple[object, object]]
) -> bool:
    key = (ref_of(before) or id(before), ref_of(after) or id(after))
    if key in pending:
        return True
    pending.add(key)
    old, old_beside = follow(before, docs.before)
    new, new_beside = follow(after, docs.after)
    if not _same(old_beside, new_beside, docs, pending, names=False):
        return False
    if old is None or new is None:
        # Nothing to resolve to, so nothing but the reference as written to compare.
        return old is None and new is None and ref_of(before) == ref_of(after)
    return _same(old, new, docs, pending, names=False)


def differing(before: Mapping[str, Any], after: Mapping[str, Any], docs: Docs) -> list[str]:
    """The keys of two objects whose values do not mean the same, editorial keys aside.

    Each key is compared inside an object of its own, so a key that maps names (``headers``,
    ``parameters``) is read as one.
    """

    def alone(node: Mapping[str, Any], key: str) -> dict[str, Any]:
        return {key: node[key]} if key in node else {}

    return sorted(
        key
        for key in (before.keys() | after.keys()) - EDITORIAL
        if not same(alone(before, key), alone(after, key), docs)
    )


def beyond(node: Any, read: tuple[str, ...]) -> dict[str, Any]:
    """*node* without the keys a rule reads: what is left for :func:`differing` to compare."""
    return {key: value for key, value in mapping(node).items() if key not in read}


__all__ = [
    "EDITORIAL",
    "SCHEMA_REF",
    "Change",
    "Docs",
    "beyond",
    "differing",
    "follow",
    "mapping",
    "ref_of",
    "refs_in",
    "resolve",
    "same",
    "schemas_of",
    "shape",
    "unclassified",
]
