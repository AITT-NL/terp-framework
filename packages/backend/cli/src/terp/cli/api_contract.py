"""``api-contract`` — the app's committed API contract, and the drift check that pins it.

An app is reached by more than its own frontend: a native mobile client, a site built in
another repository, a partner's integration. Each is compiled against the shape of the API at
one moment and then runs against whatever the app serves afterwards, and a version already
installed on a phone cannot be recalled. The production profile rightly hides the schema
endpoints, so the shape has to travel as a file: ``openapi.json`` at the project root,
written by ``terp openapi`` and committed (ADR 0194).

This module compares that file with the document the composed app exports and reports every
difference in the vocabulary of the change, the breaking ones first, the way the authority
baseline does (ADR 0139). The pin is exact: an additive change is drift too, because the
committed file is what other repositories pin. The classification is advice to the reviewer
— the control is the exact pin, so a line labelled wrongly can mislabel a change but never
let one through.

*Breaking* means a client built against the committed contract fails against the new one,
and it is decided from the client's side: a request is breaking when the new schema refuses
something the old one accepted, a response when the new schema may produce something the old
one never did.
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import Iterator, Mapping
from typing import Any

from terp.cli.api_contract_schemas import (
    REQUEST,
    RESPONSE,
    Change,
    Docs,
    changed_refs,
    diff_schema,
    mapping,
    resolve,
    schemas_of,
)

#: The committed contract, at the project root where ``terp openapi`` writes it by default.
CONTRACT_ARTIFACT = "openapi.json"

#: What an app runs to adopt the check, and again — in the same change, with the diff in front
#: of a reviewer — to accept a change to its API.
ADOPT_HINT = "uv run terp openapi, then commit openapi.json"

#: The HTTP methods an OpenAPI path item may carry an operation under.
_METHODS = ("get", "put", "post", "delete", "patch", "head", "options", "trace")

#: Keys that describe a document without changing any shape a client depends on.
_EDITORIAL = frozenset(
    {"description", "summary", "title", "tags", "operationId", "examples", "example", "externalDocs"}
)

def read_contract(root: pathlib.Path) -> dict[str, Any]:
    """The committed contract as a document; raises ``ValueError`` when it is not one."""
    text = (root / CONTRACT_ARTIFACT).read_text(encoding="utf-8")
    document = json.loads(text)
    if not isinstance(document, dict):
        raise ValueError(f"{CONTRACT_ARTIFACT} is not a JSON object")
    return document


def diff_contract(before: Mapping[str, Any], after: Mapping[str, Any]) -> list[Change]:
    """Every difference from *before* (committed) to *after* (live), breaking lines first.

    Returns an empty list exactly when the two documents are equal. When they differ in a way
    no rule below classifies, one unlabelled line says so, so a difference is never silent.
    """
    if before == after:
        return []
    changes: list[Change] = []
    docs = Docs(before, after, changed_refs(before, after))
    before_paths = mapping(before.get("paths"))
    after_paths = mapping(after.get("paths"))
    for path in sorted(before_paths.keys() | after_paths.keys()):
        was = _operations(before_paths.get(path))
        now = _operations(after_paths.get(path))
        for method in sorted(was.keys() | now.keys()):
            where = f"{method.upper()} {path}"
            if method not in now:
                changes.append(Change(True, where, "operation removed"))
            elif method not in was:
                changes.append(Change(False, where, "new operation"))
            else:
                changes.extend(
                    _diff_operation(where, was[method], now[method], docs)
                )
    changes.extend(_diff_schema_names(before, after))
    if not changes:
        changes.append(_unclassified(before, after))
    return sorted(set(changes), key=lambda change: (not change.breaking, change.where, change.what))


def render_changes(changes: list[Change]) -> str:
    """The changes as the indented lines a failing check prints."""
    return "\n".join(f"  - {change.render()}" for change in changes)


# --------------------------------------------------------------------------- #
# operations
# --------------------------------------------------------------------------- #


def _operations(path_item: Any) -> dict[str, dict[str, Any]]:
    item = mapping(path_item)
    return {method: mapping(item[method]) for method in _METHODS if method in item}


def _diff_operation(
    where: str, was: Mapping[str, Any], now: Mapping[str, Any], docs: Docs
) -> Iterator[Change]:
    yield from _diff_parameters(where, was, now, docs)
    yield from _diff_request_body(where, was.get("requestBody"), now.get("requestBody"), docs)
    yield from _diff_responses(where, mapping(was.get("responses")), mapping(now.get("responses")), docs)


def _parameters(operation: Mapping[str, Any], document: Mapping[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    found: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in operation.get("parameters") or ():
        parameter = resolve(raw, document)
        if "name" in parameter and "in" in parameter:
            found[(str(parameter["in"]), str(parameter["name"]))] = parameter
    return found


def _diff_parameters(
    where: str, was: Mapping[str, Any], now: Mapping[str, Any], docs: Docs
) -> Iterator[Change]:
    before = _parameters(was, docs.before)
    after = _parameters(now, docs.after)
    for key in sorted(before.keys() | after.keys()):
        location, name = key
        label = f"{location} parameter '{name}'"
        if key not in after:
            yield Change(True, where, f"{label} removed - a client that sends it is no longer understood")
            continue
        required = bool(after[key].get("required"))
        if key not in before:
            if required:
                yield Change(True, where, f"{label} is new and required")
            else:
                yield Change(False, where, f"new optional {label}")
            continue
        was_required = bool(before[key].get("required"))
        if required and not was_required:
            yield Change(True, where, f"{label} is now required")
        elif was_required and not required:
            yield Change(False, where, f"{label} is now optional")
        yield from diff_schema(
            where, label, before[key].get("schema"), after[key].get("schema"), REQUEST, docs
        )


def _diff_request_body(where: str, was: Any, now: Any, docs: Docs) -> Iterator[Change]:
    before = resolve(was, docs.before) if was is not None else None
    after = resolve(now, docs.after) if now is not None else None
    if before is None and after is None:
        return
    if after is None:
        yield Change(True, where, "request body removed - a client that sends one is refused or ignored")
        return
    if before is None:
        if after.get("required"):
            yield Change(True, where, "a request body is now required")
        else:
            yield Change(False, where, "accepts an optional request body")
        return
    if after.get("required") and not before.get("required"):
        yield Change(True, where, "the request body is now required")
    yield from _diff_content(where, "request body", before, after, REQUEST, docs)


def _is_success(status: str) -> bool:
    """A 2xx status, or the ``2XX`` range OpenAPI allows in its place."""
    return status.startswith("2")


def _diff_responses(
    where: str, was: Mapping[str, Any], now: Mapping[str, Any], docs: Docs
) -> Iterator[Change]:
    for status in sorted(was.keys() | now.keys()):
        if not _is_success(status):
            continue
        if status not in now:
            yield Change(True, where, f"success response {status} removed")
            continue
        if status not in was:
            yield Change(False, where, f"new success response {status}")
            continue
        before = resolve(was[status], docs.before)
        after = resolve(now[status], docs.after)
        yield from _diff_content(where, f"response {status}", before, after, RESPONSE, docs)


def _diff_content(
    where: str,
    label: str,
    was: Mapping[str, Any],
    now: Mapping[str, Any],
    direction: str,
    docs: Docs,
) -> Iterator[Change]:
    before = mapping(was.get("content"))
    after = mapping(now.get("content"))
    for media in sorted(before.keys() | after.keys()):
        if media not in after:
            yield Change(True, where, f"{label} no longer offers {media}")
        elif media not in before:
            yield Change(False, where, f"{label} also offers {media}")
        else:
            yield from diff_schema(
                where,
                label,
                mapping(before[media]).get("schema"),
                mapping(after[media]).get("schema"),
                direction,
                docs,
            )


# --------------------------------------------------------------------------- #
# what the operations do not cover
# --------------------------------------------------------------------------- #


def _diff_schema_names(before: Mapping[str, Any], after: Mapping[str, Any]) -> Iterator[Change]:
    """A schema renamed or dropped changes no wire shape, and a client that regenerates follows."""
    old = set(schemas_of(before))
    new = set(schemas_of(after))
    for name in sorted(old - new):
        yield Change(False, f"schema {name}", "removed - a client that refers to it by name must follow")
    for name in sorted(new - old):
        yield Change(False, f"schema {name}", "new")


def _strip(node: Any) -> Any:
    if isinstance(node, Mapping):
        return {key: _strip(value) for key, value in node.items() if key not in _EDITORIAL}
    if isinstance(node, list):
        return [_strip(item) for item in node]
    return node


def _unclassified(before: Mapping[str, Any], after: Mapping[str, Any]) -> Change:
    if _strip(before) == _strip(after):
        return Change(
            False,
            "contract",
            "text changed (a description, summary, title, tag or operation id) and no shape did",
        )
    return Change(
        False,
        "contract",
        "changed in a way this check does not classify (an error response, a union, a "
        "security scheme, a server or another field outside the operations' shapes)",
    )


__all__ = [
    "ADOPT_HINT",
    "CONTRACT_ARTIFACT",
    "Change",
    "diff_contract",
    "read_contract",
    "render_changes",
]
