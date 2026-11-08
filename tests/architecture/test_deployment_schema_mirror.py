"""The deployment declaration's words are the Terp Standard's, carried as a checked mirror.

terp-spec is only a development dependency of the framework, so the harness cannot read
the spec at run time: terp-arch ships ``deployment-declaration.schema.json`` byte for
byte, and the reader applies that copy rather than a restatement of it (ADR 0184
decision 8). What is held here:

* the mirror equals the spec's schema when the pinned release is the one it names, and
  while the pin is older it is not the pinned release's file (:mod:`.spec_copies`; no skip
  that could outlive the window);
* the reader's own vocabulary agrees with the schema it reads;
* the small validator applies every keyword the schema uses, and refuses any other;
* the datastore table is in the corpus's format, and the production profiles pin it.
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest
import terp_spec
import yaml

from terp.arch.deployment import SCHEMA_FILE, SPEC_RELEASE, published_table
from terp.arch.deployment import _jsonschema as jsonschema
from terp.arch.deployment import reader, standard
from terp.arch.deployment.datastores import (
    DatastoreTableError,
    load_table,
    parse_image,
    read_table,
    SOURCES,
)
from terp.cli.workbench import KNOWN_ROLES as WORKBENCH_ROLES
from tests.architecture import spec_copies

_REPO = pathlib.Path(__file__).resolve().parents[2]
_MIRROR = (
    _REPO / "packages" / "backend" / "arch" / "src" / "terp" / "arch" / "deployment" / SCHEMA_FILE
)


# --- the mirror ------------------------------------------------------------


def test_the_mirror_is_the_spec_schema_of_the_release_it_names() -> None:
    """Byte for byte against the pinned spec when the pin is SPEC_RELEASE.

    While the pin is older the comparison cannot be made, and saying so is the
    assertion: the pinned spec carries no such file, or another version of it, never
    this one. A spec release that ships this schema under an older version, a pin that
    moved without the mirror, and a pin newer than SPEC_RELEASE fail here rather than
    passing on a skip.
    """
    found = spec_copies.findings(
        {SCHEMA_FILE: _MIRROR.read_bytes()},
        terp_spec.spec_dir(),
        terp_spec.spec_version(),
        SPEC_RELEASE,
    )
    assert found == []


_ONE, _TWO = b'{"v": 1}\n', b'{"v": 2}\n'


@pytest.mark.parametrize(
    ("pinned", "release", "published", "copies", "expected"),
    [
        # The pin is the release the copies name: every file there, byte for byte.
        ("0.40.0", "0.40.0", {"a": _ONE}, {"a": _ONE}, None),
        ("0.40.0", "0.40.0", {"a": _ONE}, {"a": _TWO}, "this repository's a differs from terp-spec 0.40.0's"),
        ("0.40.0", "0.40.0", {}, {"a": _ONE}, "terp-spec 0.40.0 ships no a"),
        # The pin is older: the copies' release is not published yet.
        ("0.39.0", "0.40.0", {}, {"a": _ONE}, None),
        ("0.40.0", "0.41.0", {"a": _ONE}, {"a": _TWO}, None),  # a later change to a published file
        ("0.40.0", "0.41.0", {"a": _ONE, "b": _ONE}, {"a": _TWO, "b": _ONE}, None),  # b unchanged
        ("0.40.0", "0.41.0", {"a": _ONE}, {"a": _ONE}, "terp-spec 0.40.0 already carries a as they are here"),
        ("0.40.0", "0.41.0", {"a": _ONE, "b": _ONE}, {"a": _ONE, "b": _ONE}, "move SPEC_RELEASE to 0.40.0"),
        # The pin is newer: the pin moved and the copies' release did not.
        ("0.41.0", "0.40.0", {"a": _ONE}, {"a": _ONE}, "terp-spec 0.41.0 is pinned, newer than SPEC_RELEASE 0.40.0"),
        ("0.40.10", "0.40.9", {"a": _ONE}, {"a": _ONE}, "newer than SPEC_RELEASE 0.40.9"),
    ],
)
def test_a_copy_is_held_to_its_release_however_the_pin_stands(
    tmp_path, pinned, release, published, copies, expected
) -> None:
    """Every case of :mod:`.spec_copies`, with stand-in spec releases.

    The second schema version is the case this rule was written for: once the spec
    publishes the file, a later change to it must pass until its own release is pinned.
    """
    for name, data in published.items():
        (tmp_path / name).write_bytes(data)
    found = spec_copies.findings(copies, tmp_path, pinned, release)
    if expected is None:
        assert found == []
    else:
        assert len(found) == 1 and expected in found[0], found


def test_the_mirror_is_lf_on_every_checkout() -> None:
    """A byte comparison with a CRLF checkout would fail on Windows for no reason."""
    attributes = (_REPO / ".gitattributes").read_text(encoding="utf-8")
    assert f"{SCHEMA_FILE} text eol=lf" in attributes
    assert b"\r\n" not in _MIRROR.read_bytes()


def test_the_reader_reads_exactly_the_fields_the_schema_declares() -> None:
    schema = reader.schema()
    unit = schema["else"]["properties"]["units"]["items"]["properties"]
    assert set(reader.UNIT_FIELDS) == set(unit), "every unit field has an attribute, and no other"
    assert reader.SUPPORTED_VERSIONS == {schema["else"]["properties"]["schemaVersion"]["const"]}
    assert set(reader.role_resolved_fields()) <= set(unit)
    assert set(reader._DECLARED_KEYS) == set(schema["else"]["properties"]) - {"schemaVersion"}


#: The generator block's words at terp-spec 0.40.0, the release the signer's floor (terp-arch
#: 0.35.0) mirrors and so the oldest a signed release can name: read from that release's schema.
_GENERATOR_WORDS_AT_THE_FLOOR = {"systemPackages"}


def test_each_generator_word_newer_than_the_floor_names_its_release() -> None:
    """``terp promote`` reads an older release's declaration with this schema, and refuses a word
    the older release does not have by :data:`standard.WORDS_SINCE`. So the table holds exactly the
    generator words this reader reads that the floor's release did not have, each at a release no
    newer than the mirror's, and a declaration using one reads into the typed declaration."""
    generator = reader.schema()["else"]["properties"]["generator"]["properties"]
    newer = {f"generator.{word}" for word in set(generator) - _GENERATOR_WORDS_AT_THE_FLOOR}
    assert {path for path in standard.WORDS_SINCE if path.startswith("generator.")} == newer
    assert all(standard._release(release) <= standard._release(SPEC_RELEASE) for release in standard.WORDS_SINCE.values())
    raw = json.loads((_REPO / "tests" / "architecture" / "generator_goldens" / "static-site" / "deployment.json").read_text(encoding="utf-8"))
    declared, findings = reader.read(raw, published_table())
    assert findings == [] and declared is not None and declared.recipes == (("site", "static-site"),)
    assert standard.words_newer_than(raw, "0.44.0") == ["generator.recipes (terp-spec 0.45.0)"]
    assert standard.words_newer_than(raw, "0.45.0") == standard.words_newer_than({"generator": {}}, "0.40.0") == []
    assert standard.words_newer_than("not an object", "0.40.0") == []
    for number in ("next", "0.45.0rc1"):
        with pytest.raises(ValueError, match="is not a Terp Standard release number"):
            standard.words_newer_than(raw, number)


def test_the_roles_share_the_development_declaration_s_words() -> None:
    """One word per thing across both files, where it means the same thing."""
    assert WORKBENCH_ROLES <= set(reader.known_roles())


def test_every_pattern_ends_at_the_end_of_the_input() -> None:
    """Python's ``$`` matches before a final newline; the schema's patterns do not."""
    for pattern in re.findall(r'"pattern": "([^"]+)"', _MIRROR.read_text(encoding="utf-8")):
        assert pattern.endswith("(?![\\\\s\\\\S])"), pattern


# --- the validator ---------------------------------------------------------


def test_the_validator_refuses_a_keyword_it_does_not_apply() -> None:
    with pytest.raises(jsonschema.UnsupportedSchemaError, match="oneOf"):
        jsonschema.check_schema({"type": "object", "properties": {"a": {"oneOf": []}}})
    with pytest.raises(jsonschema.UnsupportedSchemaError, match="type"):
        jsonschema.check_schema({"type": "null"})
    with pytest.raises(jsonschema.UnsupportedSchemaError, match="additionalProperties"):
        jsonschema.check_schema({"additionalProperties": {"type": "string"}})
    jsonschema.check_schema(reader.schema())


@pytest.mark.parametrize(
    ("instance", "schema", "expected"),
    [
        (True, {"enum": [1]}, "is true (allowed: 1)"),
        (True, {"const": 1}, "is true (allowed: 1)"),
        (1.0, {"const": 1}, None),
        (2.0, {"type": "integer"}, None),
        (2.5, {"type": "integer"}, "must be a whole number, not a number"),
        (True, {"type": "number"}, "must be a number, not true or false"),
        (None, {"type": "string"}, "must be a string, not null"),
        ({}, {"type": "array"}, "must be a list, not an object"),
        ("ab", {"type": "string", "minLength": 3}, "is shorter than 3 character(s)"),
        ("abcd", {"type": "string", "maxLength": 3}, "is 4 characters long (at most 3)"),
        (
            "a\nb",
            {"type": "string", "pattern": "^[a-z]*(?![\\s\\S])"},
            "control character (U+000A)",
        ),
        ("A", {"type": "string", "pattern": "^[a-z]*(?![\\s\\S])"}, 'is "A", which does not match'),
        (0, {"type": "number", "minimum": 1}, "is 0 (allowed: at least 1)"),
        (0, {"type": "number", "exclusiveMinimum": 0}, "is 0 (allowed: more than 0)"),
        ([1, 2], {"type": "array", "maxItems": 1}, "has 2 items (allowed: at most 1)"),
        ([1, True], {"type": "array", "uniqueItems": True}, None),
        ([[1], [1]], {"type": "array", "uniqueItems": True}, "lists [1] more than once"),
        (
            [{"a": 1}, {"a": 1}],
            {"type": "array", "uniqueItems": True},
            'lists {"a": 1} more than once',
        ),
        (
            {"x": 1},
            {"type": "object", "additionalProperties": False},
            "x is not a field of the declaration (allowed: nothing)",
        ),
        (
            {"kind": "x"},
            {"type": "object", "dependentRequired": {"kind": ["version"]}},
            "version is required beside kind",
        ),
        (
            {},
            {"type": "object", "if": {"required": ["a"]}, "else": {"required": ["b"]}},
            "b is required",
        ),
        (
            {"a": 1},
            {"type": "object", "if": {"required": ["a"]}, "then": {"required": ["c"]}},
            "c is required",
        ),
        ({}, {"type": "object", "if": {"required": ["a"]}}, None),
        ("x", {"type": "string"}, None),
    ],
)
def test_a_keyword_applies_by_the_instance_s_type(instance, schema, expected) -> None:
    problems = jsonschema.validate(instance, schema)
    if expected is None:
        assert problems == []
    else:
        assert any(
            expected in f"{problem.path} {problem.detail}".strip() for problem in problems
        ), problems


# --- the datastore table ---------------------------------------------------


def test_the_published_table_is_in_the_corpus_format_and_its_sources_are_recorded() -> None:
    raw = json.loads((_MIRROR.parent / "datastore-table.json").read_text(encoding="utf-8"))
    assert set(raw) == {"kinds"}
    table = read_table(raw)
    for entry in table.entries:
        assert re.fullmatch(r"[a-z0-9./-]+@sha256:[0-9a-f]{64}", entry.image), entry
        assert (entry.kind, entry.version) in SOURCES, "every digest says where it came from"
    assert set(SOURCES) == {(entry.kind, entry.version) for entry in table.entries}
    assert published_table().describe() == "postgres 17"


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ({"kinds": {}, "extra": 1}, "nothing else"),
        ([], "nothing else"),
        ({"kinds": {"postgres": {"role": "database"}}}, "exactly a role and versions"),
        ({"kinds": {"postgres": {"role": "cache", "versions": {}}}}, "unknown role"),
        (
            {"kinds": {"postgres": {"role": "database", "versions": {"17": "postgres:17-alpine"}}}},
            "by digest alone",
        ),
        ({"kinds": {"postgres": {"role": "database", "versions": {"17": 3}}}}, "by digest alone"),
    ],
)
def test_a_table_in_another_shape_is_refused(raw, message) -> None:
    with pytest.raises(DatastoreTableError, match=message):
        read_table(raw)


@pytest.mark.parametrize(
    ("reference", "repository", "tag", "digest"),
    [
        ("postgres", "docker.io/library/postgres", None, None),
        ("library/postgres:17", "docker.io/library/postgres", "17", None),
        ("bitnami/postgresql@sha256:ab", "docker.io/bitnami/postgresql", None, "sha256:ab"),
        ("ghcr.io/example/db:1@sha256:ab", "ghcr.io/example/db", "1", "sha256:ab"),
        ("localhost:5000/db", "localhost:5000/db", None, None),
        ("localhost/db", "localhost/db", None, None),
    ],
)
def test_an_image_reference_is_taken_apart_the_way_docker_reads_it(
    reference, repository, tag, digest
) -> None:
    parsed = parse_image(reference)
    assert (parsed.repository, parsed.tag, parsed.digest) == (repository, tag, digest)


@pytest.mark.parametrize("reference", ["", "postgres@", ":17"])
def test_an_unreadable_image_reference_is_none(reference) -> None:
    assert parse_image(reference) is None


def test_a_table_entry_never_matches_what_is_not_an_image() -> None:
    entry = published_table().entries[0]
    assert not entry.pinned_by(None) and not entry.runs_its_repository(None)
    assert not entry.runs_its_repository(":")


def test_a_table_is_read_from_a_file_or_falls_back_to_the_published_one(tmp_path) -> None:
    assert load_table(None) is published_table()
    path = tmp_path / "datastore-table.json"
    path.write_text(
        json.dumps(
            {"kinds": {"redis": {"role": "store", "versions": {"7": "redis@sha256:" + "7d" * 32}}}}
        ),
        encoding="utf-8",
    )
    assert load_table(path).describe() == "redis 7"
    assert load_table(path).find("postgres", "17") is None


@pytest.mark.parametrize(
    "path",
    [
        "template/project/docker-compose.prod.yml.jinja",
        "apps/example/docker-compose.prod.yml",
        "apps/reference/overlay/docker-compose.prod.yml",
    ],
)
def test_every_production_profile_pins_its_database_to_the_table(path) -> None:
    """ADR 0184 decision 3: the template and the example pin the table's digest."""
    from tests.architecture.deployment_fixtures import answer_files

    text = (
        answer_files((_REPO / path).read_text(encoding="utf-8"), False)
        .replace("{{ project_slug }}", "app")
        .replace("{{ project_name }}", "App")
    )
    db = yaml.safe_load(text)["services"]["db"]
    assert published_table().find("postgres", "17").pinned_by(db["image"]), db["image"]
