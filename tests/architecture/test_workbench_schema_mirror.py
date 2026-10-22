"""The development-loop declaration's words are the Terp Standard's, carried as a checked mirror.

``workbench-declaration.schema.json`` is the vocabulary of ``workbench.json`` (ADR 0186).
terp-spec is only a development dependency of the framework, so terp-arch ships the schema
byte for byte (:mod:`terp.arch.workbench`), and this suite carries the spec's fixtures beside
it for the reader's own tests. What is held here:

* the mirror and the fixtures equal the spec's the moment a pinned release carries them,
  and until then the pin is honestly one that does not (no skip that could outlive the
  window);
* every list the gate's checker uses is the schema's, and nothing restates one;
* every fixture reads as it says through the gate's own reader, :func:`terp.cli.workbench.read`
  -- a valid document resolves to exactly the facts the fixture lists, an invalid one is
  refused with a message that names its field;
* the files this repository ships read cleanly.
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest
import terp_spec

from terp.arch import workbench as vocabulary
from terp.arch.deployment import _jsonschema
from terp.arch.deployment.reader import DEV_COMPOSE_FILE
from terp.cli import workbench

_REPO = pathlib.Path(__file__).resolve().parents[2]
_MIRROR = (
    _REPO / "packages" / "backend" / "arch" / "src" / "terp" / "arch" / "workbench"
    / vocabulary.SCHEMA_FILE
)
_FIXTURES_FILE = "workbench-declaration.fixtures.json"
_FIXTURES_COPY = pathlib.Path(__file__).resolve().with_name(_FIXTURES_FILE)
_FIXTURES = json.loads(_FIXTURES_COPY.read_text(encoding="utf-8"))
_SCHEMA = json.loads(_MIRROR.read_text(encoding="utf-8"))


def _version(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split("."))


# --- the mirror ------------------------------------------------------------


@pytest.mark.parametrize(("ours", "name"), [(_MIRROR, vocabulary.SCHEMA_FILE), (_FIXTURES_COPY, _FIXTURES_FILE)])
def test_the_copies_are_the_spec_s_once_a_pinned_release_carries_them(ours, name) -> None:
    """Byte for byte against the pinned spec, from the release ``SPEC_RELEASE`` names onward.

    Before that release is pinned the comparison cannot be made, and saying so is the
    assertion: the installed spec must be older than SPEC_RELEASE AND carry no such file.
    The day the pin moves the first branch takes over, and a pin that moved without the
    copies fails here rather than passing on a skip.
    """
    installed = terp_spec.spec_version()
    published = terp_spec.spec_dir() / name
    if _version(installed) >= _version(vocabulary.SPEC_RELEASE):
        assert published.is_file(), f"terp-spec {installed} ships no {name}"
        assert ours.read_bytes() == published.read_bytes(), (
            f"this repository's {name} differs from terp-spec {installed}'s: copy the spec's "
            "file over it, then make the reader honour whatever changed"
        )
    else:
        assert not published.is_file(), (
            f"terp-spec {installed} already carries {name}: move SPEC_RELEASE to it"
        )


@pytest.mark.parametrize("copy", [_MIRROR, _FIXTURES_COPY])
def test_the_copies_are_lf_on_every_checkout(copy) -> None:
    attributes = (_REPO / ".gitattributes").read_text(encoding="utf-8")
    assert f"{copy.relative_to(_REPO).as_posix()} text eol=lf" in attributes
    assert b"\r\n" not in copy.read_bytes()


def test_every_pattern_ends_at_the_end_of_the_input() -> None:
    """Python's ``$`` matches before a final newline; the schema's patterns do not."""
    text = _MIRROR.read_text(encoding="utf-8")
    patterns = re.findall(r'"pattern": "([^"]+)"', text) + re.findall(r'"(\^[^"]+)": \{', text)
    assert len(patterns) >= 10
    for pattern in patterns:
        assert pattern.endswith("(?![\\\\s\\\\S])"), pattern


def test_the_validator_applies_every_keyword_the_schema_uses() -> None:
    _jsonschema.check_schema(_SCHEMA)
    assert vocabulary.SCHEMA == _SCHEMA


# --- the lists are the schema's ----------------------------------------------


def test_every_list_the_checker_uses_is_the_schema_s() -> None:
    declared = _SCHEMA["else"]["properties"]
    definitions = _SCHEMA["$defs"]
    assert workbench.SUPPORTED_VERSIONS == {declared["schemaVersion"]["const"]} == {1}
    assert workbench.COMMAND_SLOTS == set(declared["commands"]["properties"])
    assert workbench.KNOWN_ROLES == set(definitions["knownRoles"]["enum"])
    assert workbench.ROLE_RESOLVED_FIELDS == tuple(definitions["roleResolvedFields"]["enum"])
    assert workbench.DEPLOYMENT_PROFILE_MARKERS == tuple(
        definitions["deploymentProfileMarkers"]["enum"]
    )
    assert vocabulary.ENV_SEAMS == set(declared["env"]["properties"])
    assert vocabulary.RESERVED_ENV_PREFIXES == tuple(definitions["reservedEnvironmentPrefixes"]["enum"])
    assert vocabulary.RESERVED_ENV_NAMES == set(definitions["reservedEnvironmentNames"]["enum"])
    assert workbench.WORKBENCH_FILE == vocabulary.WORKBENCH_FILE == "workbench.json"


def test_the_slots_a_workbench_runs_are_slots_the_checker_knows() -> None:
    """The drift this vocabulary ended: two slots a workbench ran were unknown here."""
    assert {"containerLogs", "recreate"} <= workbench.COMMAND_SLOTS


def test_both_readers_in_this_repository_agree_on_the_development_file() -> None:
    assert vocabulary.DEFAULT_COMPOSE_FILE == DEV_COMPOSE_FILE == workbench.Declaration().compose_file


def test_no_list_is_restated_in_the_checker() -> None:
    """A literal set of slots or roles beside the vocabulary is how the two drifted."""
    source = pathlib.Path(workbench.__file__).read_text(encoding="utf-8")
    for word in ('"resetData"', '"one-shot"', '"readinessPath"', "frozenset({1})", '".prod."'):
        assert word not in source, f"{word} is restated in terp.cli.workbench"


# --- the fixtures, read by the gate's own reader -------------------------------


def _documents(expect: str) -> list[dict]:
    return [case for case in _FIXTURES["documents"] if case["expect"] == expect]


def _reads(declared: workbench.Declaration) -> dict:
    """The facts a reader resolves, in the fixtures' shape."""
    if declared.unmanaged:
        return {"state": "unmanaged", "reason": declared.reason}
    roles: dict[str, dict[str, str]] = {}
    for entry in declared.services:
        if entry.get("role") not in workbench.KNOWN_ROLES:
            continue
        resolved = roles.setdefault(entry["role"], {})
        for name in ("service", *workbench.ROLE_RESOLVED_FIELDS):
            if name in entry and name not in resolved:
                resolved[name] = entry[name]
    return {
        "state": "declared",
        "composeFile": declared.compose_file,
        "roles": roles,
        "env": {label: name for label, name in declared.env.items() if label in vocabulary.ENV_SEAMS},
        "commands": declared.commands,
    }


@pytest.mark.parametrize("case", _documents("valid"), ids=lambda case: case["id"])
def test_a_valid_fixture_reads_as_it_says(case) -> None:
    declared, findings = workbench.read(case["document"])
    assert findings == [], case["about"]
    assert declared is not None and _reads(declared) == case["reads"], case["about"]


@pytest.mark.parametrize("case", _documents("invalid"), ids=lambda case: case["id"])
def test_an_invalid_fixture_is_refused_at_its_field(case) -> None:
    declared, findings = workbench.read(case["document"])
    assert declared is None and findings, case["about"]
    said = " ".join(f"{finding.message} {finding.remedy}" for finding in findings)
    field = case["field"].removeprefix("$.")
    if field == "$":
        assert "JSON object" in said, said
    else:
        assert field in said or field.rsplit(".", 1)[-1] in said, (
            f"{case['id']} ({case['about']}): the refusal does not name {field}: {said}"
        )


@pytest.mark.parametrize("case", _FIXTURES["texts"], ids=lambda case: case["id"])
def test_a_text_fixture_is_refused_as_unreadable(case, tmp_path) -> None:
    (tmp_path / workbench.WORKBENCH_FILE).write_text(case["text"], encoding="utf-8")
    declared, findings = workbench.load(tmp_path)
    assert declared is None and findings and "could not be read" in findings[0].message


def test_a_later_version_says_the_toolchain_is_behind() -> None:
    for document in ({"schemaVersion": 2, "services": []}, {"unmanaged": True, "reason": "x", "schemaVersion": 2}):
        _, findings = workbench.read(document)
        assert "does not read" in findings[0].message and "behind" in findings[0].remedy


# --- the shipped declarations ---------------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["template/project/workbench.json", "apps/example/workbench.json", "apps/reference/overlay/workbench.json"],
)
def test_every_shipped_declaration_reads_cleanly(path) -> None:
    declared, findings = workbench.read(json.loads((_REPO / path).read_text(encoding="utf-8")))
    assert findings == [] and declared is not None, findings
