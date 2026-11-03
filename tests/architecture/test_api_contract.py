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
import pathlib
import subprocess
import sys
import uuid
from typing import Any

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CLI_SRC = _REPO_ROOT / "packages" / "backend" / "cli" / "src"
sys.path.insert(0, str(_CLI_SRC))

from terp.cli import main  # noqa: E402
from terp.cli.api_contract import (  # noqa: E402
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
        "GET /things: new success response 2XX",
    ]
    only_errors = doc({"/things": {"get": {"responses": {"422": ok({"type": "string"})}}}})
    assert lines(doc({"/things": {"get": {"responses": {"422": ok({"type": "object"})}}}}), only_errors) == [
        "contract: changed in a way this check does not classify (an error response, a union, a "
        "security scheme, a server or another field outside the operations' shapes)"
    ]


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


def test_bounds_on_a_response_and_on_a_null_member_are_not_a_sender_s_problem() -> None:
    assert lines(get({"type": "string", "maxLength": 10}), get({"type": "string", "maxLength": 5})) == [
        "contract: changed in a way this check does not classify (an error response, a union, a "
        "security scheme, a server or another field outside the operations' shapes)"
    ]
    before = {"anyOf": [{"type": "string", "maxLength": 5}, {"type": "null", "maxLength": 1}]}
    after = {"anyOf": [{"type": "string", "maxLength": 5}, {"type": "null", "maxLength": 2}]}
    assert lines(post(before), post(after)) == [
        "contract: changed in a way this check does not classify (an error response, a union, a "
        "security scheme, a server or another field outside the operations' shapes)"
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
        "contract: changed in a way this check does not classify (an error response, a union, a "
        "security scheme, a server or another field outside the operations' shapes)"
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
    def get_note(note_id: int) -> Any:  # pragma: no cover - the schema is read, never served
        return None

    return app


def _tracked(root: pathlib.Path, contract: str) -> None:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / CONTRACT_ARTIFACT).write_text(contract, encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", CONTRACT_ARTIFACT], check=True)


def _serving(monkeypatch: pytest.MonkeyPatch, app: Any) -> None:
    import terp.cli._appref as appref

    monkeypatch.setattr(appref, "push_app_root", lambda _root: None)
    monkeypatch.setattr(appref, "load_app", lambda _ref: app)


def test_an_untracked_contract_is_a_skip_that_names_how_to_adopt_it(tmp_path: pathlib.Path) -> None:
    from terp.cli.verify import NOTE_PREFIX, _run_api_contract

    (tmp_path / CONTRACT_ARTIFACT).write_text("{}", encoding="utf-8")
    exit_code, output = _run_api_contract(tmp_path)
    assert exit_code == 0
    assert output.startswith(NOTE_PREFIX) and ADOPT_HINT in output


def test_without_git_the_check_is_red_rather_than_a_skip(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
    import terp.cli.verify as verify_module

    def missing(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError(2, "No such file or directory", argv[0])

    monkeypatch.setattr(verify_module.subprocess, "run", missing)
    exit_code, output = verify_module._run_api_contract(tmp_path)
    assert exit_code == 127
    assert "git: executable not found on PATH" in output


def test_a_tracked_contract_that_is_not_json_is_red(tmp_path: pathlib.Path) -> None:
    from terp.cli.verify import _run_api_contract

    _tracked(tmp_path, "{not json")
    exit_code, output = _run_api_contract(tmp_path)
    assert exit_code == 1
    assert "is tracked but is not a readable JSON document" in output


def test_a_tracked_contract_with_no_importable_app_is_a_named_skip(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
    import terp.cli._appref as appref
    from terp.cli.verify import NOTE_PREFIX, _run_api_contract

    def refuse(_ref: str) -> Any:
        raise SystemExit("no app")

    _tracked(tmp_path, "{}")
    monkeypatch.setattr(appref, "push_app_root", lambda _root: None)
    monkeypatch.setattr(appref, "load_app", refuse)
    exit_code, output = _run_api_contract(tmp_path)
    assert exit_code == 0
    assert output.startswith(NOTE_PREFIX) and "no importable app.main:app" in output


def test_a_tracked_contract_equal_to_the_app_passes(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
    from terp.cli.openapi import openapi_document
    from terp.cli.verify import _run_api_contract

    app = _fixture_app(title=True)
    _tracked(tmp_path, json.dumps(openapi_document(app), indent=2, sort_keys=True) + "\n")
    _serving(monkeypatch, app)
    assert _run_api_contract(tmp_path) == (0, "openapi.json matches the API the composed app serves")


def test_a_change_the_contract_does_not_record_is_red_breaking_first(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
    from terp.cli.openapi import openapi_document
    from terp.cli.verify import _run_api_contract

    _tracked(tmp_path, json.dumps(openapi_document(_fixture_app(title=True))))
    _serving(monkeypatch, _fixture_app(title=False))
    exit_code, output = _run_api_contract(tmp_path)
    assert exit_code == 1
    assert "1 of them breaking" in output
    assert "BREAKING GET /notes/{note_id}: response 200 field 'title' removed" in output
    assert "IN THE SAME CHANGE" in output and ADOPT_HINT in output


def test_the_check_is_reached_through_its_runner(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
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
def get_note(note_id: int) -> NoteRead:  # pragma: no cover - the schema is read, never served
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


class _Tree:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files

    def has(self, path: str) -> bool:
        return path in self.files

    def bytes(self, path: str) -> bytes:
        return self.files[path]


def test_a_release_carries_the_contract_its_commit_holds_and_nothing_when_there_is_none() -> None:
    from terp.cli.release import manifest
    from terp.cli.release._common import sha256

    assert manifest.carried_contract(_Tree({})) == {}
    content = b'{"openapi": "3.1.0"}\n'
    assert manifest.carried_contract(_Tree({CONTRACT_ARTIFACT: content})) == {
        "contract": {"path": CONTRACT_ARTIFACT, "sha256": sha256(content), "content": content.decode()}
    }


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
