"""The app's committed API contract and the check that pins it (ADR 0194).

A client that is not the app's own frontend, a native app already installed or a site built
in another repository, runs against whatever the app serves next. These tests hold three
things: the comparator names each difference from the client's side, breaking lines first;
the ``api-contract`` check has exactly the three states ADR 0139 settled (untracked, equal,
different) and refuses to guess where git cannot answer; and the writers around it
(``terp openapi``, ``api-client``, ``terp release``) treat a tracked contract as a reviewed
artifact rather than a scratch file.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import uuid
from typing import Any

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CLI_SRC = _REPO_ROOT / "packages" / "backend" / "cli" / "src"
sys.path.insert(0, str(_CLI_SRC))

from terp.cli import main
from terp.cli.api_contract_shapes import Docs, same
from terp.cli.api_contract import (
    ADOPT_HINT,
    CONTRACT_ARTIFACT,
    Change,
    diff_contract,
    read_contract,
    render_changes,
)

# --------------------------------------------------------------------------- #
# document builders: the smallest OpenAPI shapes each rule needs
# --------------------------------------------------------------------------- #


def doc(paths: dict[str, Any] | None = None, schemas: dict[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
    return {
        "openapi": "3.1.0",
        "info": {"title": "fixture", "version": "1"},
        "paths": paths or {},
        "components": {"schemas": schemas or {}},
        **extra,
    }


def ok(schema: Any, media: str = "application/json") -> dict[str, Any]:
    return {"description": "ok", "content": {media: {"schema": schema}}}


def body(schema: Any, *, required: bool = True, media: str = "application/json") -> dict[str, Any]:
    return {"required": required, "content": {media: {"schema": schema}}}


def param(name: str, *, where: str = "query", required: bool = False, schema: Any = None) -> dict[str, Any]:
    return {"name": name, "in": where, "required": required, "schema": schema or {"type": "string"}}


def obj(properties: dict[str, Any], required: tuple[str, ...] = ()) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": list(required)}


def ref(name: str) -> dict[str, str]:
    return {"$ref": f"#/components/schemas/{name}"}


def get(schema: Any, **operation: Any) -> dict[str, Any]:
    """One ``GET /things`` whose 200 response is *schema*."""
    return doc({"/things": {"get": {"responses": {"200": ok(schema)}, **operation}}})


def post(schema: Any, *, required: bool = True, **operation: Any) -> dict[str, Any]:
    """One ``POST /things`` whose request body is *schema*."""
    return doc({"/things": {"post": {"requestBody": body(schema, required=required), "responses": {"201": ok({"type": "object"})}, **operation}}})


def lines(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    return [change.render() for change in diff_contract(before, after)]


# --------------------------------------------------------------------------- #
# the comparator: operations
# --------------------------------------------------------------------------- #


def test_two_equal_documents_have_no_difference_at_all() -> None:
    document = get(obj({"id": {"type": "integer"}}, ("id",)))
    assert diff_contract(document, json.loads(json.dumps(document))) == []


def test_an_operation_removed_is_breaking_and_a_new_one_is_not() -> None:
    before = doc({"/a": {"get": {"responses": {}}, "post": {"responses": {}}}, "/gone": {"delete": {"responses": {}}}})
    after = doc({"/a": {"get": {"responses": {}}}, "/new": {"put": {"responses": {}}}})
    assert lines(before, after) == [
        "BREAKING DELETE /gone: operation removed",
        "BREAKING POST /a: operation removed",
        "PUT /new: new operation",
    ]


def test_keys_of_a_path_item_that_are_not_methods_are_not_operations() -> None:
    before = doc({"/a": {"summary": "x", "parameters": [], "get": {"responses": {}}}})
    after = doc({"/a": {"summary": "y", "parameters": [], "get": {"responses": {}}}})
    assert lines(before, after) == [
        "contract: text changed (a description, summary, title, tag or operation id) and no shape did"
    ]


# --------------------------------------------------------------------------- #
# parameters
# --------------------------------------------------------------------------- #


def _with_parameters(*parameters: dict[str, Any], components: dict[str, Any] | None = None) -> dict[str, Any]:
    document = doc({"/things": {"get": {"parameters": list(parameters), "responses": {}}}})
    if components:
        document["components"]["parameters"] = components
    return document


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        ([param("q")], [], "BREAKING GET /things: query parameter 'q' removed - a client that sends it is no longer understood"),
        ([], [param("q", required=True)], "BREAKING GET /things: query parameter 'q' is new and required"),
        ([], [param("q")], "GET /things: new optional query parameter 'q'"),
        ([param("q")], [param("q", required=True)], "BREAKING GET /things: query parameter 'q' is now required"),
        ([param("q", required=True)], [param("q")], "GET /things: query parameter 'q' is now optional"),
        (
            [param("q", schema={"type": "string", "enum": ["a", "b"]})],
            [param("q", schema={"type": "string", "enum": ["a"]})],
            "BREAKING GET /things: query parameter 'q' no longer accepts \"b\"",
        ),
        (
            [param("id", where="path", required=True, schema={"type": "integer"})],
            [param("id", where="path", required=True, schema={"type": "string"})],
            "BREAKING GET /things: path parameter 'id' no longer accepts integer",
        ),
    ],
)
def test_a_parameter_is_compared_from_the_side_of_the_client_that_sends_it(before, after, expected: str) -> None:
    assert lines(_with_parameters(*before), _with_parameters(*after)) == [expected]


def test_a_parameter_by_reference_is_resolved_and_one_without_a_name_is_ignored() -> None:
    shared = {"Q": param("q")}
    before = _with_parameters({"$ref": "#/components/parameters/Q"}, {"in": "query"}, components=shared)
    after = _with_parameters({"in": "query"}, components=shared)
    assert lines(before, after) == [
        "BREAKING GET /things: query parameter 'q' removed - a client that sends it is no longer understood"
    ]


# --------------------------------------------------------------------------- #
# request bodies
# --------------------------------------------------------------------------- #


def test_a_request_body_appearing_or_going_is_named_from_the_sender_side() -> None:
    bare = doc({"/things": {"post": {"responses": {}}}})
    required = doc({"/things": {"post": {"requestBody": body({"type": "object"}), "responses": {}}}})
    optional = doc({"/things": {"post": {"requestBody": body({"type": "object"}, required=False), "responses": {}}}})
    assert lines(bare, required) == ["BREAKING POST /things: a request body is now required"]
    assert lines(bare, optional) == ["POST /things: accepts an optional request body"]
    assert lines(required, bare) == [
        "BREAKING POST /things: request body removed - a client that sends one is refused or ignored"
    ]
    assert lines(optional, required) == ["BREAKING POST /things: the request body is now required"]


def test_a_request_media_type_removed_is_breaking_and_one_added_is_not() -> None:
    before = doc({"/things": {"post": {"requestBody": {"content": {"application/json": {"schema": {}}}}, "responses": {}}}})
    after = doc({"/things": {"post": {"requestBody": {"content": {"text/csv": {"schema": {}}}}, "responses": {}}}})
    assert lines(before, after) == [
        "BREAKING POST /things: request body no longer offers application/json",
        "POST /things: request body also offers text/csv",
    ]


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        (obj({"a": {"type": "string"}}), obj({}), "BREAKING POST /things: request body field 'a' removed - a client that sends it is refused or ignored"),
        (obj({}), obj({"a": {"type": "string"}}, ("a",)), "BREAKING POST /things: request body field 'a' is new and required"),
        (obj({}), obj({"a": {"type": "string"}}), "POST /things: new request body field 'a'"),
        (obj({"a": {"type": "string"}}), obj({"a": {"type": "string"}}, ("a",)), "BREAKING POST /things: request body field 'a' is now required"),
        (obj({"a": {"type": "string"}}, ("a",)), obj({"a": {"type": "string"}}), "POST /things: request body field 'a' is now optional"),
    ],
)
def test_a_request_field_is_breaking_when_a_sender_built_on_the_old_shape_fails(before, after, expected: str) -> None:
    assert lines(post(before), post(after)) == [expected]


# --------------------------------------------------------------------------- #
# success responses
# --------------------------------------------------------------------------- #


def test_a_success_status_removed_is_breaking_and_error_responses_are_not_classified() -> None:
    before = doc({"/things": {"get": {"responses": {"200": ok({}), "422": ok({"type": "object"})}}}})
    after = doc({"/things": {"get": {"responses": {"2XX": ok({}), "422": ok({"type": "string"})}}}})
    assert lines(before, after) == [
        "BREAKING GET /things: success response 200 removed",
        "GET /things: error response 422 changed",
        "GET /things: new success response 2XX",
    ]
    only_errors = doc({"/things": {"get": {"responses": {"422": ok({"type": "string"})}}}})
    assert lines(doc({"/things": {"get": {"responses": {"422": ok({"type": "object"})}}}}), only_errors) == [
        "GET /things: error response 422 changed"
    ]
    gone = doc({"/things": {"get": {"responses": {}}}})
    assert lines(only_errors, gone) == ["GET /things: error response 422 removed"]
    assert lines(gone, only_errors) == ["GET /things: new error response 422"]


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        (obj({"a": {"type": "string"}}, ("a",)), obj({}), "BREAKING GET /things: response 200 field 'a' removed"),
        (obj({"a": {"type": "string"}}, ("a",)), obj({"a": {"type": "string"}}), "BREAKING GET /things: response 200 field 'a' may now be absent"),
        (obj({"a": {"type": "string"}}), obj({"a": {"type": "string"}}, ("a",)), "GET /things: response 200 field 'a' is now always present"),
        (obj({}), obj({"a": {"type": "string"}}, ("a",)), "GET /things: new response 200 field 'a'"),
    ],
)
def test_a_response_field_is_breaking_when_a_reader_built_on_the_old_shape_fails(before, after, expected: str) -> None:
    assert lines(get(before), get(after)) == [expected]


def test_a_response_media_type_is_compared_like_a_request_one() -> None:
    before = doc({"/things": {"get": {"responses": {"200": ok({}, "application/json")}}}})
    after = doc({"/things": {"get": {"responses": {"200": ok({}, "text/plain")}}}})
    assert lines(before, after) == [
        "BREAKING GET /things: response 200 no longer offers application/json",
        "GET /things: response 200 also offers text/plain",
    ]


# --------------------------------------------------------------------------- #
# value sets: types, enums, formats and bounds, in both directions
# --------------------------------------------------------------------------- #

_TEXT = {"type": "string"}
_NULLABLE_TEXT = {"anyOf": [{"type": "string"}, {"type": "null"}]}


def test_a_type_is_breaking_when_it_narrows_a_request_or_widens_a_response() -> None:
    assert lines(post(obj({"a": _NULLABLE_TEXT})), post(obj({"a": _TEXT}))) == [
        "BREAKING POST /things: request body field 'a' no longer accepts null"
    ]
    assert lines(post(obj({"a": _TEXT})), post(obj({"a": _NULLABLE_TEXT}))) == [
        "POST /things: request body field 'a' type string -> null|string"
    ]
    assert lines(get(obj({"a": _TEXT})), get(obj({"a": _NULLABLE_TEXT}))) == [
        "BREAKING GET /things: response 200 field 'a' may now be null"
    ]
    assert lines(get(obj({"a": _NULLABLE_TEXT})), get(obj({"a": _TEXT}))) == [
        "GET /things: response 200 field 'a' type null|string -> string"
    ]


def test_an_integer_fits_inside_a_number_and_an_open_schema_admits_anything() -> None:
    assert lines(post({"type": "integer"}), post({"type": "number"})) == [
        "POST /things: request body type integer -> number"
    ]
    assert lines(get({"type": "integer"}), get({"type": "number"})) == [
        "BREAKING GET /things: response 200 may now be number"
    ]
    assert lines(post({}), post({"type": "string"})) == [
        "BREAKING POST /things: request body no longer accepts a value of any type"
    ]
    assert lines(get({"type": "string"}), get({})) == [
        "BREAKING GET /things: response 200 may now be a value of any type"
    ]


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        ({"type": "string", "enum": ["a", "b"]}, {"type": "string", "enum": ["a"]}, "BREAKING POST /things: request body no longer accepts \"b\""),
        ({"type": "string"}, {"type": "string", "enum": ["a"]}, "BREAKING POST /things: request body no longer accepts values it accepted"),
        ({"type": "string", "enum": ["a"]}, {"type": "string", "enum": ["a", "b"]}, "POST /things: request body accepts more values"),
        ({"type": "string", "enum": ["a"]}, {"type": "string"}, "POST /things: request body accepts more values"),
    ],
)
def test_a_request_value_set_breaks_when_it_refuses_a_value_it_accepted(before, after, expected: str) -> None:
    assert lines(post(before), post(after)) == [expected]


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        # A strict decoder in a native client refuses the whole response on a value it was
        # not built with, which is why a widened response enum is breaking.
        ({"type": "string", "enum": ["a"]}, {"type": "string", "enum": ["a", "b"]}, "BREAKING GET /things: response 200 may now return \"b\""),
        ({"type": "string", "enum": ["a"]}, {"type": "string"}, "BREAKING GET /things: response 200 may now return any value"),
        ({"type": "string", "enum": ["a", "b"]}, {"type": "string", "enum": ["a"]}, "GET /things: response 200 returns fewer values"),
        ({"const": "a"}, {"anyOf": [{"const": "a"}, {"type": "null"}]}, "BREAKING GET /things: response 200 may now be null"),
    ],
)
def test_a_response_value_set_breaks_when_it_may_produce_a_value_it_never_did(before, after, expected: str) -> None:
    assert lines(get(before), get(after)) == [expected]


def test_a_format_breaks_a_request_when_it_appears_and_a_response_when_it_goes() -> None:
    plain, dated = {"type": "string"}, {"type": "string", "format": "date"}
    assert lines(post(plain), post(dated)) == ["BREAKING POST /things: request body format none -> date"]
    assert lines(post(dated), post(plain)) == ["POST /things: request body format date -> none"]
    assert lines(get(dated), get(plain)) == ["BREAKING GET /things: response 200 format date -> none"]
    assert lines(get(plain), get(dated)) == ["GET /things: response 200 format none -> date"]


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        ({"maxLength": 10}, {"maxLength": 5}, "BREAKING POST /things: request body maxLength 10 -> 5"),
        ({}, {"maxLength": 5}, "BREAKING POST /things: request body maxLength none -> 5"),
        ({"maxLength": 5}, {"maxLength": 10}, "POST /things: request body maxLength 5 -> 10"),
        ({"maxLength": 5}, {}, "POST /things: request body maxLength 5 -> none"),
        ({"minLength": 1}, {"minLength": 2}, "BREAKING POST /things: request body minLength 1 -> 2"),
        ({}, {"minLength": 2}, "BREAKING POST /things: request body minLength none -> 2"),
        ({"minLength": 2}, {"minLength": 1}, "POST /things: request body minLength 2 -> 1"),
        ({"minLength": 2}, {}, "POST /things: request body minLength 2 -> none"),
        ({}, {"pattern": "^a$"}, "BREAKING POST /things: request body must now match '^a$'"),
        ({"pattern": "^a$"}, {}, "POST /things: request body no longer has to match '^a$'"),
    ],
)
def test_a_request_bound_breaks_when_it_tightens(before, after, expected: str) -> None:
    assert lines(post({"type": "string", **before}), post({"type": "string", **after})) == [expected]


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        ({"maxLength": 5}, {"maxLength": 10}, "BREAKING GET /things: response 200 maxLength 5 -> 10"),
        ({"maxLength": 5}, {}, "BREAKING GET /things: response 200 maxLength 5 -> none"),
        ({"maxLength": 10}, {"maxLength": 5}, "GET /things: response 200 maxLength 10 -> 5"),
        ({}, {"maxLength": 5}, "GET /things: response 200 maxLength none -> 5"),
        ({"minLength": 2}, {"minLength": 1}, "BREAKING GET /things: response 200 minLength 2 -> 1"),
        ({"minLength": 2}, {}, "BREAKING GET /things: response 200 minLength 2 -> none"),
        ({"minLength": 1}, {"minLength": 2}, "GET /things: response 200 minLength 1 -> 2"),
        ({}, {"minLength": 1}, "GET /things: response 200 minLength none -> 1"),
        ({"pattern": "^a$"}, {}, "BREAKING GET /things: response 200 may no longer match '^a$'"),
        ({"pattern": "^a$"}, {"pattern": "^b$"}, "BREAKING GET /things: response 200 may no longer match '^a$'"),
        ({}, {"pattern": "^a$"}, "GET /things: response 200 now always matches '^a$'"),
    ],
)
def test_a_response_bound_breaks_when_it_loosens(before, after, expected: str) -> None:
    """A strict generated client holds a response to the bounds it was built with, so a value
    past the old bound fails it the way a new enum value does."""
    assert lines(get({"type": "string", **before}), get({"type": "string", **after})) == [expected]


def test_a_response_bound_on_a_number_or_a_list_breaks_when_it_widens() -> None:
    at_most, at_least = {"type": "integer", "maximum": 10}, {"type": "integer", "minimum": 1}
    assert lines(get(at_most), get({**at_most, "maximum": 11})) == [
        "BREAKING GET /things: response 200 maximum 10 -> 11"
    ]
    assert lines(get(at_least), get({**at_least, "minimum": 0})) == [
        "BREAKING GET /things: response 200 minimum 1 -> 0"
    ]
    assert lines(get({**at_most, "maximum": 11}), get(at_most)) == ["GET /things: response 200 maximum 11 -> 10"]
    listed = {"type": "array", "items": {"type": "string"}, "maxItems": 3}
    assert lines(get(listed), get({**listed, "maxItems": 4})) == [
        "BREAKING GET /things: response 200 maxItems 3 -> 4"
    ]
    # OpenAPI 3.0's exclusive bound turned off lets the bound's own value through; turned on,
    # or written out as false, it lets nothing new through.
    assert lines(get({**at_most, "exclusiveMaximum": True}), get(at_most)) == [
        "BREAKING GET /things: response 200 exclusiveMaximum True -> none"
    ]
    assert lines(get({**at_most, "exclusiveMaximum": True}), get({**at_most, "exclusiveMaximum": False})) == [
        "BREAKING GET /things: response 200 exclusiveMaximum True -> False"
    ]
    assert lines(get(at_most), get({**at_most, "exclusiveMaximum": True})) == [
        "GET /things: response 200 exclusiveMaximum none -> True"
    ]
    assert lines(get(at_most), get({**at_most, "exclusiveMaximum": False})) == [
        "GET /things: response 200 exclusiveMaximum none -> False"
    ]


def test_a_bound_on_a_null_member_is_no_bound_on_the_value() -> None:
    before = {"anyOf": [{"type": "string", "maxLength": 5}, {"type": "null", "maxLength": 1}]}
    after = {"anyOf": [{"type": "string", "maxLength": 5}, {"type": "null", "maxLength": 2}]}
    assert lines(post(before), post(after)) == [
        "BREAKING POST /things: request body changed in a way this check does not classify - review it as breaking"
    ]


def test_a_non_numeric_bound_compares_as_zero_rather_than_raising() -> None:
    # OpenAPI 3.0 spells exclusiveMaximum as a boolean; it must not crash the comparison.
    assert lines(post({"type": "number", "exclusiveMaximum": True}), post({"type": "number", "exclusiveMaximum": 5})) == [
        "POST /things: request body exclusiveMaximum True -> 5"
    ]


def test_every_way_a_schema_can_name_its_types_is_read() -> None:
    assert lines(get({"type": ["string", "null"]}), get({"type": "string"})) == [
        "GET /things: response 200 type null|string -> string"
    ]
    every_kind = [None, True, 1, 1.5, "a", [1], {"a": 1}]
    assert lines(get({"enum": every_kind}), get({"enum": every_kind[:-1]})) == [
        "GET /things: response 200 returns fewer values",
        "GET /things: response 200 type array|boolean|integer|null|number|object|string -> "
        "array|boolean|integer|null|number|string",
    ]
    assert lines(get({"enum": [1]}), get({"enum": [1, 1.5]})) == [
        "BREAKING GET /things: response 200 may now be number",
        "BREAKING GET /things: response 200 may now return 1.5",
    ]
    assert lines(get({"type": "string"}), get({"type": "string", "nullable": True})) == [
        "BREAKING GET /things: response 200 may now be null"
    ]
    assert lines(get({"properties": {"a": {}}}), get({"properties": {}})) == [
        "BREAKING GET /things: response 200 field 'a' removed"
    ]
    assert lines(get({"items": {"type": "string"}}), get({"items": {"type": "integer"}})) == [
        "BREAKING GET /things: response 200 field '[]' may now be integer"
    ]


# --------------------------------------------------------------------------- #
# nesting, references and the shapes that must never loop
# --------------------------------------------------------------------------- #


def test_a_field_deep_in_a_referenced_shape_is_named_by_its_whole_path() -> None:
    def document(endpoint: dict[str, Any]) -> dict[str, Any]:
        return doc(
            {"/model": {"get": {"responses": {"200": ok(ref("Model"))}}}},
            {
                "Model": obj({"modules": {"type": "array", "items": ref("Module")}}, ("modules",)),
                "Module": obj({"endpoints": {"type": "array", "items": ref("Endpoint")}}, ("endpoints",)),
                "Endpoint": endpoint,
            },
        )

    before = document(obj({"path": _TEXT, "by_role": _TEXT}, ("path", "by_role")))
    after = document(obj({"path": _TEXT}, ("path",)))
    assert lines(before, after) == [
        "BREAKING GET /model: response 200 field 'modules[].endpoints[].by_role' removed"
    ]


def test_a_recursive_shape_is_compared_once_even_behind_a_nullable_union() -> None:
    def document(extra: dict[str, Any]) -> dict[str, Any]:
        node = obj(
            {
                "name": _TEXT,
                "children": {"type": "array", "items": ref("Node")},
                "parent": {"anyOf": [ref("Node"), {"type": "null"}]},
                **extra,
            },
            ("name",),
        )
        return doc({"/tree": {"get": {"responses": {"200": ok(ref("Node"))}}}}, {"Node": node})

    assert lines(document({}), document({"label": _TEXT})) == ["GET /tree: new response 200 field 'label'"]


def test_a_union_of_two_object_shapes_is_left_to_the_fallback() -> None:
    def document(b: dict[str, Any]) -> dict[str, Any]:
        return get({"oneOf": [obj({"a": _TEXT}), b]})

    assert lines(document(obj({"b": _TEXT})), document(obj({"c": _TEXT}))) == [
        "BREAKING GET /things: response 200 changed in a way this check does not classify - review it as breaking"
    ]


def test_a_reference_that_resolves_nowhere_reads_as_an_open_schema() -> None:
    # A dangling reference, one into another file and a loop of references each resolve
    # to the empty schema rather than raising or recursing.
    loop = {"A": ref("B"), "B": ref("A")}
    after = doc({"/things": {"get": {"responses": {"200": ok({"type": "string"})}}}}, loop)
    for broken in (ref("Missing"), {"$ref": "other.json#/Thing"}, ref("A")):
        before = doc({"/things": {"get": {"responses": {"200": ok(broken)}}}}, loop)
        assert lines(before, after) == ["GET /things: response 200 type any -> string"], broken


def test_a_renamed_schema_changes_no_wire_shape_but_is_still_named() -> None:
    before = doc({"/things": {"get": {"responses": {"200": ok(ref("Old"))}}}}, {"Old": obj({"a": _TEXT})})
    after = doc({"/things": {"get": {"responses": {"200": ok(ref("New"))}}}}, {"New": obj({"a": _TEXT})})
    assert lines(before, after) == [
        "schema New: new",
        "schema Old: removed - a client that refers to it by name must follow",
    ]


def test_breaking_lines_come_first_and_a_repeated_line_is_reported_once() -> None:
    changes = diff_contract(
        doc({"/a": {"get": {"responses": {}}}, "/z": {"get": {"responses": {}}}}),
        doc({"/b": {"get": {"responses": {}}}, "/z": {"get": {"responses": {}}, "post": {"responses": {}}}}),
    )
    assert [change.breaking for change in changes] == [True, False, False]
    assert render_changes(changes).splitlines()[0] == "  - BREAKING GET /a: operation removed"
    assert Change(False, "x", "y").render() == "x: y"


# --------------------------------------------------------------------------- #
# reading the committed file
# --------------------------------------------------------------------------- #


def test_the_contract_is_read_as_one_json_object(tmp_path: pathlib.Path) -> None:
    (tmp_path / CONTRACT_ARTIFACT).write_text('{"openapi": "3.1.0"}', encoding="utf-8")
    assert read_contract(tmp_path) == {"openapi": "3.1.0"}
    (tmp_path / CONTRACT_ARTIFACT).write_text("[1]", encoding="utf-8")
    with pytest.raises(ValueError, match="is not a JSON object"):
        read_contract(tmp_path)


def _link(link: pathlib.Path, target: str) -> None:
    try:
        os.symlink(target, link)
    except OSError:  # a Windows account without the link privilege
        pytest.skip("this account cannot create a symbolic link")


def test_a_contract_that_is_not_a_file_of_its_own_is_refused_and_never_followed(tmp_path: pathlib.Path) -> None:
    """git commits a symbolic link's own text, so a release carries that, not the contract.

    Followed, the link let the check hold the app to the file it points to and pass, while the
    signed release carried a path where the contract should be. A pipe would hold the check
    open, so whatever is not a regular file is refused before it is opened.
    """
    (tmp_path / "api.json").write_text('{"openapi": "3.1.0"}', encoding="utf-8")
    _link(tmp_path / CONTRACT_ARTIFACT, "api.json")
    with pytest.raises(ValueError, match="is a symbolic link"):
        read_contract(tmp_path)
    (tmp_path / CONTRACT_ARTIFACT).unlink()
    (tmp_path / CONTRACT_ARTIFACT).mkdir()
    with pytest.raises(ValueError, match="is not a regular file"):
        read_contract(tmp_path)


# --------------------------------------------------------------------------- #
# the api-contract check
# --------------------------------------------------------------------------- #


def _fixture_app(*, title: bool) -> Any:
    from fastapi import FastAPI
    from pydantic import create_model

    fields: dict[str, Any] = {"id": (int, ...)}
    if title:
        fields["title"] = (str, ...)
    note = create_model("NoteRead", **fields)
    app = FastAPI(title="fixture", version="1")

    @app.get("/notes/{note_id}", response_model=note)
    def get_note(note_id: int) -> Any:  # the schema is read, never served
        return None

    return app


def _tracked(root: pathlib.Path, contract: str) -> None:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / CONTRACT_ARTIFACT).write_text(contract, encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", CONTRACT_ARTIFACT], check=True)


def _serving(monkeypatch: pytest.MonkeyPatch, root: pathlib.Path, app: Any) -> None:
    """An app package at *root* that composes to *app*."""
    import terp.cli._appref as appref

    (root / "app").mkdir(exist_ok=True)
    monkeypatch.setattr(appref, "push_app_root", lambda _root: None)
    monkeypatch.setattr(appref, "load_app", lambda _ref: app)


@pytest.fixture
def own_app_package(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Let a test import an ``app`` package of its own, and leave no trace of it behind.

    Every app's package is called ``app``, so one imported earlier in the run would answer
    for this one, and this one would answer for every later import.
    """
    import terp.cli._appref as appref

    def ours(name: str) -> bool:
        return name == "app" or name.startswith("app.")

    for name in [name for name in sys.modules if ours(name)]:
        monkeypatch.delitem(sys.modules, name)
    monkeypatch.setattr(appref, "push_app_root", lambda root: monkeypatch.syspath_prepend(str(root)))
    yield
    for name in [name for name in sys.modules if ours(name)]:
        del sys.modules[name]


def test_an_untracked_contract_is_a_skip_that_names_how_to_adopt_it(tmp_path: pathlib.Path) -> None:
    from terp.cli.api_contract_check import run_api_contract_check
    from terp.cli.verify import NOTE_PREFIX

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / CONTRACT_ARTIFACT).write_text("{}", encoding="utf-8")
    exit_code, output = run_api_contract_check(tmp_path)
    assert exit_code == 0
    assert output.startswith(NOTE_PREFIX) and ADOPT_HINT in output
    assert "is not tracked" in output


def test_without_git_the_check_is_red_rather_than_a_skip(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
    import terp.cli.verify as verify_module
    from terp.cli.api_contract_check import run_api_contract_check

    def missing(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError(2, "No such file or directory", argv[0])

    monkeypatch.setattr(verify_module.subprocess, "run", missing)
    exit_code, output = run_api_contract_check(tmp_path)
    assert exit_code == 127
    assert "git: executable not found on PATH" in output
    assert "install git" in output


def test_where_git_cannot_answer_the_check_is_red_and_says_why(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
    """git exits 128 outside a work tree, and for a repository it refuses as another user's.

    Neither is "untracked". Read as one, the check skipped with a note telling the reader to
    commit a file that may already be committed, and ``api-client`` exported over it.
    """
    from terp.cli.api_contract_check import run_api_contract_check
    from terp.cli.verify import NOTE_PREFIX

    for variable in ("GIT_DIR", "GIT_WORK_TREE"):
        monkeypatch.delenv(variable, raising=False)
    # git looks no further up than this test's own directory, wherever the run happens.
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    (tmp_path / CONTRACT_ARTIFACT).write_text("{}", encoding="utf-8")
    exit_code, output = run_api_contract_check(tmp_path)
    assert exit_code == 128
    assert not output.startswith(NOTE_PREFIX)
    assert "git could not say whether openapi.json is tracked" in output
    assert "not a git repository" in output, "git's own words reach the reader"
    assert "safe.directory" in output and "git work tree" in output, "the remedy is named"


def test_where_git_cannot_answer_the_client_is_not_exported_over_the_contract(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    import terp.cli.openapi as openapi_module
    import terp.cli.verify as verify_module

    frontend = tmp_path / "frontend"
    (frontend / "node_modules").mkdir(parents=True)
    (frontend / "package.json").write_text(json.dumps({"scripts": {"generate": "x"}}), encoding="utf-8")
    refused = (
        "fatal: detected dubious ownership in repository at '/srv/example-app'\n"
        "To add an exception for this directory, call:\n\n"
        "\tgit config --global --add safe.directory /srv/example-app\n"
    )
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv[1:])
        return subprocess.CompletedProcess(argv, 128, "", refused)

    def never(**_kwargs: object) -> pathlib.Path:
        raise AssertionError("api-client exported over a contract git could not vouch for")

    monkeypatch.setattr(openapi_module, "export_openapi", never)
    monkeypatch.setattr(verify_module.subprocess, "run", fake_run)
    exit_code, output = verify_module._run_api_client(tmp_path)
    assert exit_code == 128
    assert "dubious ownership" in output and "safe.directory /srv/example-app" in output
    assert "the API client is not generated" in output
    assert calls == [["ls-files", "--error-unmatch", "--", "openapi.json"]], "npm never ran"


def test_a_tracked_contract_that_is_not_json_is_red(tmp_path: pathlib.Path) -> None:
    from terp.cli.api_contract_check import run_api_contract_check

    _tracked(tmp_path, "{not json")
    exit_code, output = run_api_contract_check(tmp_path)
    assert exit_code == 1
    assert "is tracked but is not a readable JSON document" in output


def test_a_tracked_contract_committed_as_a_link_is_red_and_names_how_to_commit_the_file(
    tmp_path: pathlib.Path,
) -> None:
    from terp.cli.api_contract_check import run_api_contract_check

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "api.json").write_text("{}", encoding="utf-8")
    _link(tmp_path / CONTRACT_ARTIFACT, "api.json")
    subprocess.run(["git", "-C", str(tmp_path), "add", CONTRACT_ARTIFACT], check=True)
    exit_code, output = run_api_contract_check(tmp_path)
    assert exit_code == 1
    assert "is a symbolic link" in output
    assert output.endswith(f"Commit the contract itself: remove {CONTRACT_ARTIFACT}, then {ADOPT_HINT}")


def test_a_tracked_contract_with_no_app_package_is_a_named_skip(tmp_path: pathlib.Path) -> None:
    from terp.cli.api_contract_check import run_api_contract_check
    from terp.cli.verify import NOTE_PREFIX

    _tracked(tmp_path, "{}")
    exit_code, output = run_api_contract_check(tmp_path)
    assert exit_code == 0
    assert output.startswith(NOTE_PREFIX) and "no app/ package" in output


def test_a_tracked_contract_whose_app_does_not_import_is_red(own_app_package: Any, tmp_path: pathlib.Path) -> None:
    """With a tracked contract ``api-client`` reads the file and never imports the app, so
    this check is what reaches it; a green note here left nothing in ``quick`` that would."""
    from terp.cli.api_contract_check import run_api_contract_check
    from terp.cli.verify import NOTE_PREFIX

    _tracked(tmp_path, "{}")
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "main.py").write_text("import terp_contract_fixture_absent_dependency  # noqa: F401\n", encoding="utf-8")
    exit_code, output = run_api_contract_check(tmp_path)
    assert exit_code == 1
    assert not output.startswith(NOTE_PREFIX)
    assert "ModuleNotFoundError" in output and "terp_contract_fixture_absent_dependency" in output
    assert "uv run terp openapi" in output, "the remedy is named"


@pytest.mark.parametrize(
    "failure",
    [SystemExit("'app.main:app' did not resolve to a FastAPI application"), RuntimeError("DATABASE_URL is not set")],
    ids=["not-an-app", "a-factory-that-raises"],
)
def test_an_app_package_that_does_not_compose_is_red_whatever_it_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path, failure: BaseException
) -> None:
    import terp.cli._appref as appref
    from terp.cli.api_contract_check import run_api_contract_check

    def refuse(_ref: str) -> Any:
        raise failure

    _tracked(tmp_path, "{}")
    (tmp_path / "app").mkdir()
    monkeypatch.setattr(appref, "push_app_root", lambda _root: None)
    monkeypatch.setattr(appref, "load_app", refuse)
    exit_code, output = run_api_contract_check(tmp_path)
    assert exit_code == 1
    assert f"{type(failure).__name__}: {failure}" in output


def test_a_tracked_contract_equal_to_the_app_passes(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
    from terp.cli.api_contract_check import run_api_contract_check
    from terp.cli.openapi import openapi_document

    app = _fixture_app(title=True)
    _tracked(tmp_path, json.dumps(openapi_document(app), indent=2, sort_keys=True) + "\n")
    _serving(monkeypatch, tmp_path, app)
    assert run_api_contract_check(tmp_path) == (0, "openapi.json matches the API the composed app serves")


def test_a_change_the_contract_does_not_record_is_red_breaking_first(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
    from terp.cli.api_contract_check import run_api_contract_check
    from terp.cli.openapi import openapi_document

    _tracked(tmp_path, json.dumps(openapi_document(_fixture_app(title=True))))
    _serving(monkeypatch, tmp_path, _fixture_app(title=False))
    exit_code, output = run_api_contract_check(tmp_path)
    assert exit_code == 1
    assert "1 of them breaking" in output
    assert "BREAKING GET /notes/{note_id}: response 200 field 'title' removed" in output
    assert "IN THE SAME CHANGE" in output and ADOPT_HINT in output


def test_the_check_is_reached_through_its_runner(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    with pytest.raises(SystemExit) as excinfo:
        main(["verify", "--profile", "quick", "--root", str(tmp_path), "--only", "api-contract", "--format", "json"])
    assert excinfo.value.code == 0
    (check,) = json.loads(capsys.readouterr().out)["checks"]
    assert check["id"] == "api-contract"
    assert "is not tracked" in check["output_tail"], "the runner ran, not its command string"


def test_the_contract_check_runs_before_the_client_is_generated_from_it() -> None:
    from terp.cli.verify import PROFILES

    for profile, checks in PROFILES.items():
        ids = [check.id for check in checks]
        assert ids.index("api-contract") == ids.index("api-client") - 1, profile


# --------------------------------------------------------------------------- #
# api-client reads a tracked contract and never rewrites it
# --------------------------------------------------------------------------- #


def test_the_client_is_generated_from_a_tracked_contract_without_exporting_over_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    import terp.cli.openapi as openapi_module
    import terp.cli.verify as verify_module

    frontend = tmp_path / "frontend"
    (frontend / "node_modules").mkdir(parents=True)
    (frontend / "package.json").write_text(json.dumps({"scripts": {"generate": "x"}}), encoding="utf-8")

    def never(**_kwargs: object) -> pathlib.Path:
        raise AssertionError("a gate check exported over a tracked contract")

    calls: list[list[str]] = []

    def fake_run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv[1:])
        return subprocess.CompletedProcess(argv, 0, "generated\n", "")

    monkeypatch.setattr(openapi_module, "export_openapi", never)
    monkeypatch.setattr(verify_module.subprocess, "run", fake_run)
    exit_code, output = verify_module._run_api_client(tmp_path)
    assert exit_code == 0
    assert output.startswith("read the committed openapi.json")
    assert calls == [["ls-files", "--error-unmatch", "--", "openapi.json"], ["--prefix", "frontend", "run", "generate"]]


# --------------------------------------------------------------------------- #
# terp openapi names what it is accepting
# --------------------------------------------------------------------------- #

_MODULE = '''\
from fastapi import FastAPI
from pydantic import BaseModel


class NoteRead(BaseModel):
    id: int


app = FastAPI(title="fixture", version="1")


@app.get("/notes/{note_id}", response_model=NoteRead)
def get_note(note_id: int) -> NoteRead:  # the schema is read, never served
    return NoteRead(id=note_id)
'''


def _module(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> str:
    name = f"contract_fixture_{uuid.uuid4().hex}"
    (tmp_path / f"{name}.py").write_text(_MODULE, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    return f"{name}:app"


def test_terp_openapi_names_each_change_before_saying_what_it_wrote(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
    from terp.cli.openapi import openapi_document, run_openapi_command

    app_ref = _module(monkeypatch, tmp_path)
    out = tmp_path / CONTRACT_ARTIFACT
    assert run_openapi_command(app_ref, out=out, app_root=tmp_path) == f"wrote {out}", "nothing to compare with"
    assert run_openapi_command(app_ref, out=out, app_root=tmp_path) == f"wrote {out}", "nothing changed"
    out.write_text(json.dumps(openapi_document(_fixture_app(title=True))), encoding="utf-8")
    first, *rest = run_openapi_command(app_ref, out=out, app_root=tmp_path).splitlines()
    assert first == "the contract changed in 1 way(s), 1 of them breaking:"
    assert rest == ["  - BREAKING GET /notes/{note_id}: response 200 field 'title' removed", f"wrote {out}"]
    out.write_text("[not a document", encoding="utf-8")
    assert run_openapi_command(app_ref, out=out, app_root=tmp_path) == f"wrote {out}", "unreadable is no baseline"
    out.write_text("[1]", encoding="utf-8")
    assert run_openapi_command(app_ref, out=out, app_root=tmp_path) == f"wrote {out}", "a list is no document"


def test_the_cli_prints_what_terp_openapi_reports(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    app_ref = _module(monkeypatch, tmp_path)
    out = tmp_path / "nested" / CONTRACT_ARTIFACT
    main(["openapi", "--app", app_ref, "--out", str(out), "--app-root", str(tmp_path)])
    assert capsys.readouterr().out.strip() == f"wrote {out}"
    assert json.loads(out.read_text(encoding="utf-8"))["paths"]


# --------------------------------------------------------------------------- #
# the signed release carries the contract
# --------------------------------------------------------------------------- #


def _tree(files: dict[str, bytes], *, mode: str = "100644") -> Any:
    """A commit's tree holding *files*, each under git *mode* (``120000`` is a link)."""
    from terp.cli.release._git import Entry, Tree

    entries = {path: Entry(mode, f"{number:040x}") for number, path in enumerate(files)}
    blobs = {entries[path].oid: data for path, data in files.items()}
    return Tree("c" * 40, "t" * 40, 0, entries, blobs)


def test_a_release_carries_the_contract_its_commit_holds_and_nothing_when_there_is_none() -> None:
    from terp.cli.release import manifest
    from terp.cli.release._common import sha256

    assert manifest.carried_contract(_tree({})) == {}
    content = b'{"openapi": "3.1.0"}\n'
    assert manifest.carried_contract(_tree({CONTRACT_ARTIFACT: content})) == {
        "contract": {"path": CONTRACT_ARTIFACT, "sha256": sha256(content), "content": content.decode()}
    }


def test_a_contract_committed_as_a_link_is_refused_rather_than_carried_as_its_text() -> None:
    """A link's blob is the path it points to. Carried, the signed release named that path
    where the contract should be, while the check had read the file at the other end."""
    from terp.cli.release import manifest
    from terp.cli.release._common import ReleaseError

    with pytest.raises(ReleaseError, match="committed as a symbolic link") as refused:
        manifest.carried_contract(_tree({CONTRACT_ARTIFACT: b"docs/api.json"}, mode="120000"))
    assert f"then uv run terp openapi, then commit {CONTRACT_ARTIFACT}" in str(refused.value)


def _manifest_with(contract: Any) -> bytes:
    from terp.cli.release._common import canonical, sha256

    carried = {"path": "deployment.json", "sha256": sha256(b"{}"), "content": "{}"}
    return canonical(
        {
            "schemaVersion": 1,
            "inputs": {
                "releaseTag": "r1",
                "build": "own",
                "spec": {"release": "0.40.0"},
                "declaration": carried,
                "profiles": [],
                "datastores": {},
                "contract": contract,
            },
            "outputs": {"images": {}, "services": {}},
            "collected": {},
        }
    )


def test_a_carried_contract_is_held_to_its_sha_like_every_carried_file() -> None:
    from terp.cli.release import manifest
    from terp.cli.release._common import ReleaseError, sha256

    good = {"path": CONTRACT_ARTIFACT, "sha256": sha256(b"{}"), "content": "{}"}
    assert manifest.parse(_manifest_with(good))["inputs"]["contract"] == good
    with pytest.raises(ReleaseError, match="is not the content its SHA-256 names"):
        manifest.parse(_manifest_with({**good, "content": "[]"}))
    with pytest.raises(ReleaseError, match="inputs.contract is missing"):
        manifest.parse(_manifest_with("openapi.json"))


# --------------------------------------------------------------------------- #
# the template commits the contract
# --------------------------------------------------------------------------- #


def test_the_template_commits_its_contract_and_generates_the_client_from_it() -> None:
    project = _REPO_ROOT / "template" / "project"
    ignored = {line.strip() for line in (project / ".gitignore").read_text(encoding="utf-8").splitlines()}
    assert not ignored & {"/openapi.json", "openapi.json"}, "the contract is the app's, so it is tracked"
    package = (project / "frontend" / "package.json.jinja").read_text(encoding="utf-8")
    assert "openapi-typescript ../openapi.json" in package


# --------------------------------------------------------------------------- #
# a difference no rule reads is never silent, and never counted as safe
# --------------------------------------------------------------------------- #

_NEW_OPERATION = {"/added": {"post": {"responses": {}}}}


def _with_new_operation(document: dict[str, Any]) -> dict[str, Any]:
    return {**document, "paths": {**document["paths"], **_NEW_OPERATION}}


@pytest.mark.parametrize(
    ("before", "after"),
    [
        # A map's value schema: the shape behind CurrentUser.module_ranks.
        (
            obj({"ranks": {"type": "object", "additionalProperties": {"type": "integer"}}}),
            obj({"ranks": {"type": "object", "additionalProperties": {"type": "string"}}}),
        ),
        (obj({"a": {"type": "string", "default": "x"}}), obj({"a": {"type": "string", "default": "y"}})),
        (obj({"a": _TEXT}), {**obj({"a": _TEXT}), "additionalProperties": False}),
    ],
)
def test_an_unread_difference_beside_other_changes_is_counted_as_breaking(before, after) -> None:
    changes = diff_contract(get(before), _with_new_operation(get(after)))
    breaking = [change.render() for change in changes if change.breaking]
    assert len(breaking) == 1, changes
    assert breaking[0].endswith("changed in a way this check does not classify - review it as breaking")
    assert "POST /added: new operation" in [change.render() for change in changes]


_UNREAD = "changed in a way this check does not classify - review it as breaking"
_A = obj({"a": _TEXT}, ("a",))
_B = obj({"b": _TEXT}, ("b",))
#: B with its one field no longer required: a response that may now come without it.
_B_LOOSER = obj({"b": _TEXT})


def _answering(schema: Any, b: dict[str, Any]) -> dict[str, Any]:
    """``GET /things`` answering *schema*, beside components A and the given B."""
    return doc({"/things": {"get": {"responses": {"200": ok(schema)}}}}, {"A": _A, "B": b})


def _with_header(schema: Any) -> dict[str, Any]:
    response = {**ok(_TEXT), "headers": {"X-Remaining": {"schema": schema}}}
    return doc({"/things": {"get": {"responses": {"200": response}}}})


def _path_parameter(*, required: bool) -> dict[str, Any]:
    return doc({"/things": {"parameters": [param("q", required=required)], "get": {"responses": {}}}})


def _styled(style: str) -> dict[str, Any]:
    return _with_parameters({**param("ids"), "style": style})


@pytest.mark.parametrize(
    ("before", "after", "line"),
    [
        pytest.param(
            _answering({"anyOf": [ref("A"), ref("B")]}, _B),
            _answering({"anyOf": [ref("A"), ref("B")]}, _B_LOOSER),
            f"BREAKING GET /things: response 200 {_UNREAD}",
            id="anyOf-of-references",
        ),
        pytest.param(
            _answering({"oneOf": [ref("A"), ref("B")]}, _B),
            _answering({"oneOf": [ref("A"), ref("B")]}, _B_LOOSER),
            f"BREAKING GET /things: response 200 {_UNREAD}",
            id="oneOf-of-references",
        ),
        pytest.param(
            _answering({"allOf": [ref("B")]}, _B),
            _answering({"allOf": [ref("B")]}, _B_LOOSER),
            f"BREAKING GET /things: response 200 {_UNREAD}",
            id="allOf",
        ),
        pytest.param(
            _answering({"type": "object", "additionalProperties": ref("B")}, _B),
            _answering({"type": "object", "additionalProperties": ref("B")}, _B_LOOSER),
            f"BREAKING GET /things: response 200 {_UNREAD}",
            id="additionalProperties-by-reference",
        ),
        pytest.param(
            _answering({"type": "array", "items": {"anyOf": [ref("A"), ref("B")]}}, _B),
            _answering({"type": "array", "items": {"anyOf": [ref("A"), ref("B")]}}, _B_LOOSER),
            f"BREAKING GET /things: response 200 field '[]' {_UNREAD}",
            id="items-a-union-of-references",
        ),
        pytest.param(
            # pydantic writes a field's default beside the reference to its type; the new
            # field beside it is what used to keep the parent's fallback quiet.
            _answering(obj({"kind": {"$ref": "#/components/schemas/A", "default": {"a": "x"}}}), _B),
            _answering(obj({"kind": {"$ref": "#/components/schemas/A", "default": {"a": "y"}}, "extra": _TEXT}), _B),
            f"BREAKING GET /things: response 200 field 'kind' {_UNREAD}",
            id="a-default-beside-a-reference",
        ),
        pytest.param(
            get(obj({"a": _TEXT})),
            get({**obj({"a": _TEXT, "c": _TEXT}), "additionalProperties": False}),
            f"BREAKING GET /things: response 200 {_UNREAD}",
            id="an-unread-keyword-where-a-field-also-changed",
        ),
        pytest.param(
            doc(schemas={"Vocabulary": _B}),
            doc(schemas={"Vocabulary": _B_LOOSER}),
            f"BREAKING schema Vocabulary: the schema, reached by no operation this check compared, {_UNREAD}",
            id="a-component-no-operation-reaches",
        ),
        pytest.param(
            _with_header({"type": "integer"}),
            _with_header({"type": "string"}),
            f"BREAKING GET /things: response 200 headers {_UNREAD}",
            id="response-headers",
        ),
        pytest.param(
            _path_parameter(required=False),
            _path_parameter(required=True),
            f"BREAKING /things: the path's parameters {_UNREAD}",
            id="path-item-parameters",
        ),
        pytest.param(
            _styled("form"),
            _styled("pipeDelimited"),
            f"BREAKING GET /things: query parameter 'ids' style {_UNREAD}",
            id="a-parameter-keyword",
        ),
        pytest.param(
            doc(info={"title": "fixture", "version": "1"}),
            doc(info={"title": "fixture", "version": "2"}),
            f"BREAKING contract: the document {_UNREAD}",
            id="the-document-root",
        ),
    ],
)
def test_a_difference_no_rule_reads_is_breaking_whatever_else_changed(before, after, line: str) -> None:
    """Each shape beside an unrelated change, which is what used to silence it.

    The fallbacks spoke only when nothing else had: a node whose field produced a line, or
    a document with one new operation, reported "0 breaking" over a change behind a union of
    references, a component no operation reached, a response header or a path's parameters.
    """
    changes = diff_contract(before, _with_new_operation(after))
    rendered = [change.render() for change in changes]
    assert sum(change.breaking for change in changes) > 0, rendered
    assert line in rendered
    assert "POST /added: new operation" in rendered


def test_a_schema_renamed_behind_a_place_no_rule_reads_is_still_only_named() -> None:
    """The unread part is compared with its references resolved, so a rename there keeps
    the verdict a rename gets anywhere: named, without the label."""
    before = _answering({"anyOf": [ref("A"), ref("B")]}, _B)
    after = doc(
        {"/things": {"get": {"responses": {"200": ok({"anyOf": [ref("A"), ref("C")]})}}}}, {"A": _A, "C": _B}
    )
    assert lines(before, after) == [
        "schema B: removed - a client that refers to it by name must follow",
        "schema C: new",
    ]


def test_an_error_schema_that_changed_is_named_without_the_label_and_only_once() -> None:
    def document(error: dict[str, Any]) -> dict[str, Any]:
        responses = {"200": ok(_TEXT), "422": ok(ref("Problem"))}
        return doc({"/things": {"get": {"responses": responses}}}, {"Problem": error})

    changes = diff_contract(document(_B), _with_new_operation(document(_B_LOOSER)))
    assert [change.render() for change in changes] == [
        "GET /things: error response 422 changed",
        "POST /added: new operation",
    ]


# Each of the comparisons behind that rule, one test apiece: the line it gives, and beside
# it a control that goes through the same comparison with the thing it reads unchanged.


def _field(schema: Any, schemas: dict[str, Any] | None = None) -> dict[str, Any]:
    """``GET /things`` answering an object whose field ``f`` is *schema*."""
    return doc({"/things": {"get": {"responses": {"200": ok(obj({"f": schema}))}}}}, schemas)


def test_what_is_said_of_a_value_is_compared_wherever_it_is_written() -> None:
    """A field that stops being nullable keeps its default, which moves off the union onto
    the value; a reference made optional moves it from beside the reference onto the union.
    Neither is a difference, and a default that really changes is still one."""
    kind = {"Kind": {"type": "string", "enum": ["a", "b"]}}
    optional = {"anyOf": [_TEXT, {"type": "null"}], "default": "x"}
    assert lines(_field(optional), _field({**_TEXT, "default": "x"})) == [
        "GET /things: response 200 field 'f' type null|string -> string"
    ]
    assert lines(_field({**ref("Kind"), "default": "a"}, kind), _field({"anyOf": [ref("Kind"), {"type": "null"}], "default": "a"}, kind)) == [
        "BREAKING GET /things: response 200 field 'f' may now be null"
    ]
    beside_member = {"anyOf": [{**ref("Kind"), "default": "a"}, {"type": "null"}]}
    moved = _field({"anyOf": [ref("Kind"), {"type": "null"}], "default": "a"}, kind)
    assert lines(_field(beside_member, kind), _with_new_operation(moved)) == ["POST /added: new operation"]
    assert lines(_field(beside_member, kind), _field({"anyOf": [{**ref("Kind"), "default": "b"}, {"type": "null"}]}, kind)) == [
        f"BREAKING GET /things: response 200 field 'f' {_UNREAD}"
    ]
    assert lines(_field(optional), _field({**_TEXT, "default": "y"})) == [
        f"BREAKING GET /things: response 200 field 'f' {_UNREAD}",
        "GET /things: response 200 field 'f' type null|string -> string",
    ]


def test_a_boolean_schema_is_compared_as_written() -> None:
    """``true`` admits everything and ``false`` nothing; no rule reads either."""
    assert lines(get({"anyOf": [True, _TEXT]}), get({"anyOf": [False, _TEXT]})) == [f"BREAKING GET /things: response 200 {_UNREAD}"]
    assert lines(get({"type": "array", "items": True}), get({"type": "array", "items": False})) == [
        f"BREAKING GET /things: response 200 field '[]' {_UNREAD}"
    ]
    # Unchanged beside a new alternative, it is no line; the alternative is the type rule's.
    assert lines(get({"anyOf": [True, _TEXT]}), get({"anyOf": [True, _TEXT, {"type": "integer"}]})) == [
        "GET /things: response 200 type any|string -> any|integer|string"
    ]


def test_a_schema_deeper_than_the_floor_is_a_line_where_the_walk_stops() -> None:
    """The floor (64 frames, two to each level of fields) ends the walk at the 32nd field, so
    a malformed document can neither hang the check nor change below it in silence."""

    def nested(depth: int, leaf: Any) -> dict[str, Any]:
        node = leaf
        for _ in range(depth):
            node = obj({"x": node})
        return get(node)

    assert lines(nested(40, _TEXT), nested(40, {"type": "integer"})) == [
        f"BREAKING GET /things: response 200 field '{'.'.join(['x'] * 32)}' {_UNREAD}"
    ]
    assert lines(nested(31, _TEXT), nested(31, {"type": "integer"})) == [
        f"BREAKING GET /things: response 200 field '{'.'.join(['x'] * 31)}' may now be integer"
    ]


def test_a_reference_back_into_a_loop_still_carries_what_is_written_beside_it() -> None:
    """The loop is compared once, where it starts; what is written beside the reference that
    closes it belongs to that field alone."""

    def tree(parent: dict[str, Any], **extra: Any) -> dict[str, Any]:
        node = obj({"name": _TEXT, "parent": parent, **extra})
        return doc({"/tree": {"get": {"responses": {"200": ok(ref("Node"))}}}}, {"Node": node})

    deprecated = {**ref("Node"), "deprecated": True}
    assert lines(tree(ref("Node")), tree(deprecated)) == [f"BREAKING GET /tree: response 200 field 'parent' {_UNREAD}"]
    assert lines(tree(deprecated), tree(deprecated, label=_TEXT)) == ["GET /tree: new response 200 field 'label'"]


def test_what_is_written_beside_a_reference_is_compared_at_every_place_it_is_written() -> None:
    # A pair of references already being compared was taken as equal before what is written
    # beside it, so a changed default was seen or missed by the order the walk met the two
    # places, which the hash seed set: "0 breaking" on five seeds of eight. A list holds the
    # order fixed here, the plain reference first, as the unlucky seeds had it.
    docs = Docs.of(doc(schemas={"A": _TEXT}), doc(schemas={"A": _TEXT}))
    plain = ref("A")
    assert not same([plain, {**plain, "default": "x"}], [plain, {**plain, "default": "y"}], docs)
    assert same([plain, {**plain, "default": "x"}], [plain, {**plain, "default": "x"}], docs)


def test_a_required_name_with_no_property_is_a_line_of_its_own() -> None:
    """The fields rule reads the names it has properties for; a sender that omits a name
    required without one is refused all the same."""
    assert lines(post(obj({"a": _TEXT}, ("a",))), post(obj({"a": _TEXT}, ("a", "ghost")))) == [
        f"BREAKING POST /things: request body {_UNREAD}"
    ]
    assert lines(post(obj({"a": _TEXT, "b": _TEXT}, ("a",))), post(obj({"a": _TEXT, "b": _TEXT}, ("a", "b")))) == [
        "BREAKING POST /things: request body field 'b' is now required"
    ]


def test_a_parameter_it_cannot_key_is_compared_as_written() -> None:
    """A parameter is matched by location and name; one with neither, or a second with the
    same pair, has nothing to be matched by, so it is compared where it stands."""
    nameless = {"in": "query", "schema": _TEXT}
    unread = f"BREAKING GET /things: a parameter it cannot tell apart by location and name {_UNREAD}"
    assert lines(_with_parameters(param("q"), nameless), _with_parameters(param("q"), {**nameless, "schema": {"type": "integer"}})) == [unread]
    assert lines(_with_parameters(param("q"), param("q")), _with_parameters(param("q"), param("q", required=True))) == [unread]
    assert lines(_with_parameters(param("q"), nameless), _with_parameters(param("q", required=True), nameless)) == [
        "BREAKING GET /things: query parameter 'q' is now required"
    ]


def test_a_difference_the_walk_reads_as_none_is_still_a_line_for_the_document() -> None:
    """The type rule reads a union of plain types as the set of them, so swapping two is no
    line where they stand. The document still differs, and the net that names it counts it
    as breaking, because it cannot tell that nothing a client reads changed; text alone is
    the one difference it names without the label."""
    assert lines(get({"anyOf": [_TEXT, {"type": "integer"}]}), get({"anyOf": [{"type": "integer"}, _TEXT]})) == [
        f"BREAKING contract: the document {_UNREAD}"
    ]
    assert lines(get({**_TEXT, "description": "a"}), get({**_TEXT, "description": "b"})) == [
        "contract: text changed (a description, summary, title, tag or operation id) and no shape did"
    ]


def test_a_recursive_schema_no_operation_reaches_is_followed_to_its_end_once() -> None:
    """Compared through its own loop, a rename inside it is only named, and a change in it
    is a line."""

    def orphan(leaf: str, required: tuple[str, ...] = ()) -> dict[str, Any]:
        return doc(schemas={"Node": obj({"next": ref("Node"), "leaf": ref(leaf)}, required), leaf: _A})

    assert lines(orphan("Leaf"), orphan("Renamed")) == [
        "schema Leaf: removed - a client that refers to it by name must follow",
        "schema Renamed: new",
    ]
    assert lines(orphan("Leaf"), orphan("Leaf", ("next",))) == [
        f"BREAKING schema Node: the schema, reached by no operation this check compared, {_UNREAD}"
    ]


def test_a_reference_in_what_no_rule_reads_is_followed_or_compared_as_written() -> None:
    """Behind ``additionalProperties`` a reference is resolved, so what is beside it counts
    and a rename does not; one that resolves nowhere is compared as written."""

    def values(target: dict[str, Any], **properties: Any) -> dict[str, Any]:
        node = {**obj(properties), "additionalProperties": target}
        return doc({"/things": {"get": {"responses": {"200": ok(node)}}}}, {"A": _A, "A2": _A})

    gone = {"$ref": "#/components/schemas/Gone"}
    unread = [f"BREAKING GET /things: response 200 {_UNREAD}"]
    assert lines(values({**ref("A"), "default": {"a": "x"}}), values({**ref("A"), "default": {"a": "y"}})) == unread
    assert lines(values(gone), values(ref("A"))) == unread
    assert lines(values(gone), values({"$ref": "#/components/schemas/AlsoGone"})) == unread
    assert lines(values(gone), values(gone, x=_TEXT)) == ["GET /things: new response 200 field 'x'"]
    renamed = values({**ref("A2"), "default": {"a": "x"}})
    del renamed["components"]["schemas"]["A"]
    assert lines(values({**ref("A"), "default": {"a": "x"}}), renamed) == [
        "schema A: removed - a client that refers to it by name must follow"
    ]


def test_a_property_named_like_an_editorial_keyword_is_still_compared() -> None:
    before = get(obj({"title": {"type": "string", "default": "a"}}))
    after = get(obj({"title": {"type": "string", "default": "b"}}))
    assert lines(before, after) == [
        "BREAKING GET /things: response 200 field 'title' changed in a way this check does not "
        "classify - review it as breaking"
    ]


def test_an_order_nothing_reads_is_not_a_difference() -> None:
    before = get(obj({"a": _TEXT, "b": _TEXT}, ("a", "b")))
    after = get(obj({"a": _TEXT, "b": _TEXT}, ("b", "a")))
    assert lines(before, after) == [
        "contract: text changed (a description, summary, title, tag or operation id) and no shape did"
    ]


def test_a_declared_security_scheme_is_compared_where_a_document_has_one() -> None:
    """A document from another generator may declare its security; Terp's writes none (below)."""

    def document(scheme: str, security: list[Any]) -> dict[str, Any]:
        base = doc({"/things": {"get": {"responses": {}, "security": security}}}, servers=[{"url": "/"}])
        base["components"]["securitySchemes"] = {"bearer": {"type": "http", "scheme": scheme}}
        return base

    assert lines(document("bearer", [{"bearer": []}]), document("basic", [{"bearer": []}])) == [
        "BREAKING contract: 'securitySchemes' changed in a way this check does not classify - review it as breaking"
    ]
    assert lines(document("bearer", [{"bearer": []}]), document("bearer", [])) == [
        "BREAKING GET /things: the operation, outside its parameters, body and responses, changed in "
        "a way this check does not classify - review it as breaking"
    ]
    moved = document("bearer", [{"bearer": []}])
    moved["servers"] = [{"url": "/v2"}]
    assert lines(document("bearer", [{"bearer": []}]), moved) == ["contract: 'servers' changed"]


def test_a_terp_contract_says_nothing_about_who_may_call_an_operation() -> None:
    """Authorization is not in the contract: ADR 0194 says so because this holds.

    Terp declares no ``security``, no ``securitySchemes`` and no 401 or 403 response, so
    moving a route from public to admin leaves the contract unchanged. The authority baseline
    (``authz-surface``, ADR 0139) is what pins who may reach what.
    """
    contract = json.loads((_REPO_ROOT / "apps" / "example" / CONTRACT_ARTIFACT).read_text(encoding="utf-8"))
    assert "security" not in contract
    assert "securitySchemes" not in contract.get("components", {})
    operations = [operation for item in contract["paths"].values() for operation in item.values()]
    assert operations, "the reference contract has operations to look at"
    for operation in operations:
        assert "security" not in operation
        assert not {"401", "403"} & set(operation.get("responses", {}))


def test_a_document_changed_only_outside_what_is_compared_is_named_as_a_whole() -> None:
    assert lines(doc(info={"x-owner": "a"}), doc(info={"x-owner": "b"})) == [
        "BREAKING contract: the document changed in a way this check does not classify - review it as breaking"
    ]


def test_a_boolean_that_became_a_number_is_a_change_although_python_reads_them_equal() -> None:
    """``true``, ``1`` and ``1.0`` are one value to ``==`` and three to a client's decoder and to
    the file ``terp openapi`` writes, so equality is decided on the contract's text."""
    for before, after in (({"const": True}, {"const": 1}), ({"enum": [True]}, {"enum": [1]})):
        found = lines(get({"type": "integer", **before}), get({"type": "integer", **after}))
        assert found and found[0].startswith("BREAKING"), (before, after, found)
    assert lines(post({"type": "integer", "maximum": 1}), post({"type": "integer", "maximum": True})) == [
        "BREAKING POST /things: request body maximum 1 -> True"
    ]


def test_an_openapi_3_0_exclusive_bound_turned_on_is_a_tightening() -> None:
    """3.0 writes ``exclusiveMaximum: true`` beside ``maximum``, refusing the bound's own value."""
    at_most = {"type": "integer", "maximum": 10}
    assert lines(post({**at_most, "exclusiveMaximum": False}), post({**at_most, "exclusiveMaximum": True})) == [
        "BREAKING POST /things: request body exclusiveMaximum False -> True"
    ]
    assert lines(post(at_most), post({**at_most, "exclusiveMaximum": True})) == [
        "BREAKING POST /things: request body exclusiveMaximum none -> True"
    ]
    assert lines(post({**at_most, "exclusiveMaximum": True}), post({**at_most, "exclusiveMaximum": False})) == [
        "POST /things: request body exclusiveMaximum True -> False"
    ]
    at_least = {"type": "integer", "minimum": 1}
    assert lines(post(at_least), post({**at_least, "exclusiveMinimum": True})) == [
        "BREAKING POST /things: request body exclusiveMinimum none -> True"
    ]


def test_an_openapi_3_0_exclusive_bound_written_false_admits_what_none_admits() -> None:
    """``false`` refuses nothing absence would accept, so writing it out is no tightening; it
    was reported as a new bound, breaking, which a reviewer learns to stop reading."""
    at_most, at_least = {"type": "integer", "maximum": 10}, {"type": "integer", "minimum": 1}
    assert lines(post(at_most), post({**at_most, "exclusiveMaximum": False})) == [
        "POST /things: request body exclusiveMaximum none -> False"
    ]
    assert lines(post(at_least), post({**at_least, "exclusiveMinimum": False})) == [
        "POST /things: request body exclusiveMinimum none -> False"
    ]
    assert lines(post({**at_least, "exclusiveMinimum": False}), post(at_least)) == [
        "POST /things: request body exclusiveMinimum False -> none"
    ]
    # A number stays a number: 0 is a bound in 3.1, not 3.0's false.
    assert lines(post({"type": "integer"}), post({"type": "integer", "exclusiveMaximum": 0})) == [
        "BREAKING POST /things: request body exclusiveMaximum none -> 0"
    ]


def test_a_document_nested_past_the_comparison_is_red_rather_than_a_traceback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """A traceback ends the run and leaves every later check of the profile unreported; a red
    line names the file and the way out."""
    from terp.cli import api_contract_check
    from terp.cli.api_contract_check import run_api_contract_check

    _tracked(tmp_path, "[" * 100_000 + "]" * 100_000)
    _serving(monkeypatch, tmp_path, _fixture_app(title=True))
    code, output = run_api_contract_check(tmp_path)
    assert code == 1 and "is tracked but is not a readable JSON document" in output

    _tracked(tmp_path, json.dumps(doc()))

    def too_deep(*_args: Any, **_kwargs: Any) -> Any:
        raise RecursionError("maximum recursion depth exceeded")

    monkeypatch.setattr(api_contract_check, "diff_contract", too_deep)
    code, output = run_api_contract_check(tmp_path)
    assert code == 1 and "nested deeper than this check compares" in output


def test_what_the_app_prints_on_import_does_not_reach_the_check_s_stdout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``terp verify --format json`` reports on stdout alone, so an app that prints when it is
    imported must not write into the verdict document."""
    import terp.cli._appref as appref
    from terp.cli.api_contract_check import run_api_contract_check

    app = _fixture_app(title=True)
    _tracked(tmp_path, json.dumps(doc()))
    _serving(monkeypatch, tmp_path, app)

    def noisy(_ref: str) -> Any:
        print("the app prints on import")
        return app

    monkeypatch.setattr(appref, "load_app", noisy)
    run_api_contract_check(tmp_path)
    captured = capsys.readouterr()
    assert captured.out == "" and "the app prints on import" in captured.err
