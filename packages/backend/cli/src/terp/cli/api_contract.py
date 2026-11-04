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
one never did. It is decided from the document, so it covers what the document says: who may
call an operation is not in a Terp contract (it declares no ``security`` and no 401 or 403),
and the authority baseline is what pins that.
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import Iterator, Mapping
from typing import Any

from terp.cli.api_contract_schemas import REQUEST, RESPONSE, diff_schema
from terp.cli.api_contract_shapes import (
    SCHEMA_REF,
    Change,
    Docs,
    beyond,
    differing,
    mapping,
    refs_in,
    resolve,
    same,
    schemas_of,
    shape,
    unclassified,
)

#: The committed contract, at the project root where ``terp openapi`` writes it by default.
CONTRACT_ARTIFACT = "openapi.json"

#: What an app runs to adopt the check, and again — in the same change, with the diff in front
#: of a reviewer — to accept a change to its API.
ADOPT_HINT = "uv run terp openapi, then commit openapi.json"

#: The HTTP methods an OpenAPI path item may carry an operation under.
_METHODS = ("get", "put", "post", "delete", "patch", "head", "options", "trace")

#: A security declaration, which a document from another generator may carry. Terp's own
#: composition writes none, so for a Terp app neither part ever changes; where a document has
#: one, a change to it is one this check cannot read, and it is breaking until reviewed.
_BREAKING_PARTS = ("security", "securitySchemes")

#: What a rule reads of a parameter, a request body, a response and a media type. The rest of
#: each is compared on its own (:func:`_unread_line`).
_PARAMETER_KEYS = ("name", "in", "required", "schema")
_BODY_KEYS = ("required", "content")
_RESPONSE_KEYS = ("content",)
_MEDIA_KEYS = ("schema",)

#: The parts of a document no other comparison here reads.
_ROOT = ("openapi", "info")


def read_contract(root: pathlib.Path) -> dict[str, Any]:
    """The committed contract as a document; raises ``ValueError`` when it is not one."""
    text = (root / CONTRACT_ARTIFACT).read_text(encoding="utf-8")
    document = json.loads(text)
    if not isinstance(document, dict):
        raise ValueError(f"{CONTRACT_ARTIFACT} is not a JSON object")
    return document


def diff_contract(before: Mapping[str, Any], after: Mapping[str, Any]) -> list[Change]:
    """Every difference from *before* (committed) to *after* (live), breaking lines first.

    Returns an empty list exactly when the two documents are equal. A difference no rule
    classifies is a breaking line of its own, naming the place, wherever it sits and whatever
    else changed; text that changes no shape is one unlabelled line, and only when nothing
    else changed.
    """
    if before == after:
        return []
    changes: list[Change] = []
    docs = Docs.of(before, after)
    before_paths = mapping(before.get("paths"))
    after_paths = mapping(after.get("paths"))
    for path in sorted(before_paths.keys() | after_paths.keys()):
        if path in before_paths and path in after_paths:
            changes.extend(_diff_path_item(path, before_paths[path], after_paths[path], docs))
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
    changes.extend(_diff_document_parts(before, after, docs))
    # Last, because it reads what the walk above accounted for.
    changes.extend(_diff_unreached_schemas(docs))
    if not same({key: before.get(key) for key in _ROOT}, {key: after.get(key) for key in _ROOT}, docs):
        changes.append(unclassified("contract", "the document"))
    if not changes:
        changes.append(_unclassified(before, after))
    return sorted(set(changes), key=lambda change: (not change.breaking, change.where, change.what))


def render_changes(changes: list[Change]) -> str:
    """The changes as the indented lines a failing check prints."""
    return "\n".join(f"  - {change.render()}" for change in changes)


def _unread_line(where: str, subject: str, was: Any, now: Any, read: tuple[str, ...], docs: Docs) -> Iterator[Change]:
    """One line for what no rule reads of an object (a response's ``headers``, a parameter's
    ``style``, a media type's ``encoding``), naming the keys that differ."""
    old, new = beyond(was, read), beyond(now, read)
    keys = differing(old, new, docs)
    if keys:
        docs.cover(old, new)
        yield unclassified(where, f"{subject} {', '.join(keys)}")


# --------------------------------------------------------------------------- #
# operations
# --------------------------------------------------------------------------- #


def _operations(path_item: Any) -> dict[str, dict[str, Any]]:
    item = mapping(path_item)
    return {method: mapping(item[method]) for method in _METHODS if method in item}


def _diff_path_item(path: str, was: Any, now: Any, docs: Docs) -> Iterator[Change]:
    """What a path says beside its operations: parameters every operation takes, servers."""
    yield from _unread_line(path, "the path's", was, now, _METHODS, docs)


def _diff_operation(
    where: str, was: Mapping[str, Any], now: Mapping[str, Any], docs: Docs
) -> Iterator[Change]:
    modelled = ("parameters", "requestBody", "responses")
    rest_before = {key: value for key, value in was.items() if key not in modelled}
    rest_after = {key: value for key, value in now.items() if key not in modelled}
    if shape(rest_before) != shape(rest_after) or not same(rest_before, rest_after, docs):
        # Its security requirement, a callback, a deprecation: nothing below reads them.
        docs.cover(rest_before, rest_after)
        yield unclassified(where, "the operation, outside its parameters, body and responses,")
    yield from _diff_parameters(where, was, now, docs)
    yield from _diff_request_body(where, was.get("requestBody"), now.get("requestBody"), docs)
    yield from _diff_responses(where, mapping(was.get("responses")), mapping(now.get("responses")), docs)


def _parameters(
    operation: Mapping[str, Any], document: Mapping[str, Any]
) -> tuple[dict[tuple[str, str], dict[str, Any]], list[Any]]:
    """The parameters by location and name, and the ones that cannot be told apart that way."""
    found: dict[tuple[str, str], dict[str, Any]] = {}
    apart: list[Any] = []
    for raw in operation.get("parameters") or ():
        parameter = resolve(raw, document)
        key = (str(parameter.get("in")), str(parameter.get("name")))
        if "name" in parameter and "in" in parameter and key not in found:
            found[key] = parameter
        else:
            apart.append(raw)
    return found, apart


def _diff_parameters(
    where: str, was: Mapping[str, Any], now: Mapping[str, Any], docs: Docs
) -> Iterator[Change]:
    before, old_apart = _parameters(was, docs.before)
    after, new_apart = _parameters(now, docs.after)
    if not same(old_apart, new_apart, docs):
        docs.cover(old_apart, new_apart)
        yield unclassified(where, "a parameter it cannot tell apart by location and name")
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
        yield from _unread_line(where, label, before[key], after[key], _PARAMETER_KEYS, docs)
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
    yield from _unread_line(where, "request body", before, after, _BODY_KEYS, docs)
    yield from _diff_content(where, "request body", before, after, REQUEST, docs)


def _is_success(status: str) -> bool:
    """A 2xx status, or the ``2XX`` range OpenAPI allows in its place."""
    return status.startswith("2")


def _diff_responses(
    where: str, was: Mapping[str, Any], now: Mapping[str, Any], docs: Docs
) -> Iterator[Change]:
    for status in sorted(was.keys() | now.keys()):
        if not _is_success(status):
            yield from _diff_error_response(where, status, was.get(status), now.get(status), docs)
            continue
        if status not in now:
            yield Change(True, where, f"success response {status} removed")
            continue
        if status not in was:
            yield Change(False, where, f"new success response {status}")
            continue
        before = resolve(was[status], docs.before)
        after = resolve(now[status], docs.after)
        yield from _unread_line(where, f"response {status}", before, after, _RESPONSE_KEYS, docs)
        yield from _diff_content(where, f"response {status}", before, after, RESPONSE, docs)


def _diff_error_response(where: str, status: str, was: Any, now: Any, docs: Docs) -> Iterator[Change]:
    """An error response is not classified, but a change to one is never silent.

    Terp answers every error with one envelope, so a change here is rarely a break; it is
    still a line, because a client that decodes an error body strictly reads it.
    """
    if now is None:
        yield Change(False, where, f"error response {status} removed")
    elif was is None:
        yield Change(False, where, f"new error response {status}")
    else:
        before, after = resolve(was, docs.before), resolve(now, docs.after)
        if (
            shape(before) != shape(after)
            or (refs_in(before) | refs_in(after)) & docs.changed
            or not same(before, after, docs)
        ):
            docs.cover(before, after)
            yield Change(False, where, f"error response {status} changed")


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
            yield from _unread_line(where, f"{label} {media}", before[media], after[media], _MEDIA_KEYS, docs)
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


def _diff_unreached_schemas(docs: Docs) -> Iterator[Change]:
    """A component schema that changed where no comparison above accounted for it.

    The walk enters a component wherever an operation compared here reaches it. One that only
    a new or a removed operation uses, or none does (a vocabulary a client is typed against),
    would otherwise change in silence beside any other line.
    """
    old, new = schemas_of(docs.before), schemas_of(docs.after)
    for name in sorted(old.keys() & new.keys()):
        reference = {"$ref": SCHEMA_REF + name}
        if (
            reference["$ref"] not in docs.covered
            and shape(old[name]) != shape(new[name])
            and not same(reference, reference, docs)
        ):
            yield unclassified(f"schema {name}", "the schema, reached by no operation this check compared,")


def _diff_document_parts(before: Mapping[str, Any], after: Mapping[str, Any], docs: Docs) -> Iterator[Change]:
    """Everything outside the operations and the schema list, compared on every run.

    A declared security scheme or requirement is breaking until reviewed (Terp writes none);
    any other part a client may read (servers, reusable parameters or responses) is named
    without the label.
    """
    old_parts = {key: value for key, value in before.items() if key not in ("paths", "components", *_ROOT)}
    new_parts = {key: value for key, value in after.items() if key not in ("paths", "components", *_ROOT)}
    old_parts.update({key: value for key, value in mapping(before.get("components")).items() if key != "schemas"})
    new_parts.update({key: value for key, value in mapping(after.get("components")).items() if key != "schemas"})
    for key in sorted(old_parts.keys() | new_parts.keys()):
        old, new = old_parts.get(key), new_parts.get(key)
        if shape(old) != shape(new) or not same(old, new, docs):
            if key in _BREAKING_PARTS:
                yield unclassified("contract", f"'{key}'")
            else:
                yield Change(False, "contract", f"'{key}' changed")


def _unclassified(before: Mapping[str, Any], after: Mapping[str, Any]) -> Change:
    """The one line for a difference nothing above named."""
    if shape(before) == shape(after):
        return Change(
            False,
            "contract",
            "text changed (a description, summary, title, tag or operation id) and no shape did",
        )
    return unclassified("contract", "the document")


__all__ = [
    "ADOPT_HINT",
    "CONTRACT_ARTIFACT",
    "Change",
    "diff_contract",
    "read_contract",
    "render_changes",
]
