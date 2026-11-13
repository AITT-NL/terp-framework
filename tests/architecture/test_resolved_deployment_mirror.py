"""The resolved deployment's words are terp-spec's, carried as checked copies.

``resolved-deployment.schema.json`` is the vocabulary of the document ``terp release sign``
writes at a manifest's ``outputs.deployment``. terp-spec is only a development dependency of
the framework, so terp-arch ships the schema byte for byte
(:mod:`terp.arch.deployment.resolved_check`), and this suite carries the spec's fixtures beside
it for the checker's own tests. What is held here:

* the schema and the fixtures equal the spec's when the pinned release is the one
  ``SPEC_RELEASE`` names, and while the pin is older they are not both the pinned release's
  files (:mod:`.spec_copies`; no skip that could outlive the window);
* every fixture reads as it says through :func:`~terp.arch.deployment.resolved_check.refusals`:
  a valid document is refused by nothing, an invalid one at the field its fixture names, and
  one the schema cannot refuse (``beyondSchema``) passes the schema and is refused with the
  fixture's own words for what the field allows;
* a document of any shape is read without raising.
"""

from __future__ import annotations

import copy
import json
import pathlib
from typing import Any

import pytest
import terp_spec

from terp.arch.deployment import _jsonschema, resolved_check
from tests.architecture import spec_copies

_REPO = pathlib.Path(__file__).resolve().parents[2]
_SCHEMA_COPY = (
    _REPO / "packages" / "backend" / "arch" / "src" / "terp" / "arch" / "deployment"
    / resolved_check.SCHEMA_FILE
)
_FIXTURES_FILE = "resolved-deployment.fixtures.json"
_FIXTURES_COPY = pathlib.Path(__file__).resolve().with_name(_FIXTURES_FILE)
_FIXTURES = json.loads(_FIXTURES_COPY.read_text(encoding="utf-8"))
_CASES = {case["id"]: case for case in _FIXTURES["documents"]}


def test_the_copies_are_the_spec_s_of_the_release_they_name() -> None:
    """Byte for byte against the pinned spec when the pin is ``SPEC_RELEASE``.

    While the pin is older the comparison cannot be made, and saying so is the assertion:
    the pinned spec does not carry both copies as they are here.
    """
    found = spec_copies.findings(
        {resolved_check.SCHEMA_FILE: _SCHEMA_COPY.read_bytes(), _FIXTURES_FILE: _FIXTURES_COPY.read_bytes()},
        terp_spec.spec_dir(),
        terp_spec.spec_version(),
        resolved_check.SPEC_RELEASE,
    )
    assert found == []


@pytest.mark.parametrize("copied", [_SCHEMA_COPY, _FIXTURES_COPY])
def test_the_copies_are_lf_on_every_checkout(copied: pathlib.Path) -> None:
    attributes = (_REPO / ".gitattributes").read_text(encoding="utf-8")
    assert f"{copied.relative_to(_REPO).as_posix()} text eol=lf" in attributes
    assert b"\r\n" not in copied.read_bytes()


_ITS_OWN = object()


def _refusals(case: dict[str, Any], document: Any = _ITS_OWN) -> list[tuple[str, str]]:
    release = _FIXTURES["releases"][case["release"]]
    return resolved_check.refusals(
        case["document"] if document is _ITS_OWN else document,
        units=[(unit["id"], unit["role"], unit.get("kind"), unit.get("version")) for unit in release["units"]],
        images=release["images"],
        datastores={(entry["kind"], entry["version"]): entry["image"] for entry in release["datastores"]},
    )


@pytest.mark.parametrize("ident", [ident for ident, case in _CASES.items() if case["expect"] == "valid"])
def test_a_valid_document_is_refused_by_nothing(ident: str) -> None:
    assert _refusals(_CASES[ident]) == []


@pytest.mark.parametrize("ident", [ident for ident, case in _CASES.items() if case["expect"] == "invalid"])
def test_an_invalid_document_is_refused_at_the_field_its_fixture_names(ident: str) -> None:
    case = _CASES[ident]
    found = _refusals(case)
    if case.get("beyondSchema"):
        assert _jsonschema.validate(case["document"], resolved_check.SCHEMA) == [], (
            f"{ident}: the fixture says the schema cannot refuse it"
        )
        assert (case["field"], case["allowed"]) in found, f"{ident}: {found}"
    else:
        assert case["field"] in {field for field, _ in found}, f"{ident}: {found}"


def test_a_repeated_item_is_named_where_it_repeats() -> None:
    found = _refusals(_CASES["invalid-45"])
    assert ("$.volumes[1]", 'lists "db-data" more than once') in found


def _mistyped() -> list[tuple[str, Any]]:
    valid = _CASES["valid-01"]["document"]
    cases: list[tuple[str, Any]] = [("a list", []), ("a string", "services"), ("nothing", None)]
    for where, value in (
        ("services", {"db": {}}), ("services[0]", "db"), ("services[0].id", ["db"]),
        ("services[0].environment", {"A": "b"}), ("services[0].environment[0]", ["A"]),
        ("services[0].environment[0].name", 7), ("services[0].mounts[0]", 3),
        ("services[0].mounts[0].target", {"path": "/"}), ("services[0].after", "api"),
        ("services[1].after[0]", 1), ("services[1].after[0].unit", ["db"]),
        ("services[0].datastore", "postgres"), ("volumes", {"db-data": {}}),
        ("volumes[0]", 5), ("migration", ["migrate"]),
    ):
        document = copy.deepcopy(valid)
        holder, key = _locate(document, where)
        holder[key] = value
        cases.append((where, document))
    return cases


def _locate(document: Any, where: str) -> tuple[Any, Any]:
    steps: list[Any] = []
    for part in where.split("."):
        name, _, index = part.partition("[")
        steps.append(name)
        if index:
            steps.append(int(index.rstrip("]")))
    holder = document
    for step in steps[:-1]:
        holder = holder[step]
    return holder, steps[-1]


@pytest.mark.parametrize(("where", "document"), _mistyped(), ids=[where for where, _ in _mistyped()])
def test_a_mistyped_value_is_refused_and_never_raises(where: str, document: Any) -> None:
    assert _refusals(_CASES["valid-01"], document) != []
