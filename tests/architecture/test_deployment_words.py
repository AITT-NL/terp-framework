"""A deployment-declaration refusal names its field and what it allows, as every reader does.

terp-spec's fixtures state the words; ``test_deployment_fixtures`` holds the framework's
messages to them case by case. This holds what the fixtures leave out: the refusals no
corpus case carries, the strict parse every reader shares, and a message that never
carries a control character or passes an odd key off as a deeper path.
"""

from __future__ import annotations

import copy
import json
import pathlib

import pytest

from terp.arch.deployment import _words, published_table, read
from terp.arch.deployment._jsonschema import Problem
from terp.arch.deployment.files import ConstantError, DuplicateKeyError, load, loads
from tests.architecture.deployment_fixtures import seed, unit


def _messages(raw: object) -> str:
    declared, findings = read(raw, published_table())
    assert declared is None and findings, "expected the reader to refuse this declaration"
    return "\n".join(finding.message for finding in findings)


def _generated() -> dict:
    raw = seed()
    raw["build"] = "generated"
    return raw


# --- one file, read one way ----------------------------------------------------------


def test_a_key_written_twice_in_one_object_is_refused_not_read_as_its_last_value(
    tmp_path: pathlib.Path,
) -> None:
    """terp-runner refuses a key twice in one object; a reader that kept the last value
    would pass a file the deploy then refuses, or read a value the deploy never sees."""
    text = json.dumps(seed()).replace('"build": "own"', '"build": "managed", "build": "own"', 1)
    assert '"build": "managed", "build": "own"' in text
    with pytest.raises(DuplicateKeyError, match='the key "build" appears twice in one object'):
        loads(text)
    (tmp_path / "deployment.json").write_text(text, encoding="utf-8")
    declared, findings = load(tmp_path, published_table())
    assert declared is None
    assert [finding.message for finding in findings] == [
        'deployment.json is not strict JSON: the key "build" appears twice in one object '
        "(allowed: one JSON object, each key once)"
    ]
    assert loads(json.dumps(seed())) == seed(), "a file with each key once reads as it did"


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_a_number_that_is_not_json_is_refused_not_read_as_a_float(
    tmp_path: pathlib.Path, constant: str
) -> None:
    """Python's parser reads ``NaN`` and the infinities, and terp-runner refuses them. Read
    here, a size of ``NaN`` cores passed ``terp check`` and was refused at the deploy."""
    raw = seed()
    raw["sizes"] = {"small": {"cpu": 0.5, "memoryMiB": 256}}
    text = json.dumps(raw).replace('"cpu": 0.5', f'"cpu": {constant}', 1)
    assert f'"cpu": {constant}' in text
    with pytest.raises(ConstantError, match=f"{constant} is not a JSON number"):
        loads(text)
    (tmp_path / "deployment.json").write_text(text, encoding="utf-8")
    declared, findings = load(tmp_path, published_table())
    assert declared is None
    assert [finding.message for finding in findings] == [
        f"deployment.json is not strict JSON: {constant} is not a JSON number "
        "(allowed: one JSON object, each number finite)"
    ]


# --- no control character, no odd key passed off as a path ---------------------------


def test_a_key_with_a_control_character_is_written_escaped_never_raw() -> None:
    raw = seed()
    raw["x\u001b[31mRED"] = 1
    raw["a.b c"] = 1
    message = _messages(raw)
    assert "\u001b" not in message
    assert '["x\\u001b[31mRED"] is not a field of the declaration' in message
    assert '["a.b c"] is not a field of the declaration' in message, "a dot is no deeper path"


def test_a_value_with_an_eight_bit_control_character_is_written_escaped() -> None:
    """``json.dumps`` writes U+007F to U+009F as they are; the message escapes them."""
    raw = seed()
    unit(raw, "api")["healthPath"] = "/health\u009b31m"
    message = _messages(raw)
    assert "\u009b" not in message
    assert "U+009B" in message or "\\u009b" in message


# --- each refusal in the vocabulary's own words --------------------------------------


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (
            lambda raw: unit(raw, "db").pop("kind"),
            "units[0].kind is required beside version (allowed: the datastore kind, declared "
            "with its version: postgres",
        ),
        (
            lambda raw: unit(raw, "db").pop("version"),
            "units[0].version is required beside kind (allowed: the datastore version, declared "
            "with its kind: 17 for postgres)",
        ),
        (
            lambda raw: unit(raw, "db").update(kind=5),
            "units[0].kind must be a string, not a number (allowed: a datastore kind of the "
            "table: postgres",
        ),
        (
            lambda raw: unit(raw, "db").update(version=17),
            "units[0].version must be a string, not a number (allowed: the datastore version, "
            "declared with its kind: 17 for postgres)",
        ),
        (
            lambda raw: raw.update({"$comment": 5}),
            "$comment must be a string, not a number (allowed: an annotation: text without "
            "control characters)",
        ),
        (
            lambda raw: raw.update(rollback={}),
            "rollback.strategy is required (allowed: ",
        ),
        (
            lambda raw: raw.update(volumes=[{"id": "files", "mount": {"path": 5, "units": ["api"]}}]),
            "volumes[0].mount.path must be a string, not a number (allowed: the value the "
            "vocabulary gives this field)",
        ),
        (
            lambda raw: raw.update(colour="blue"),
            "colour is not a field of the declaration (allowed: the top-level keys: build, "
            "compose, externalDatabase, rollback, schemaVersion, sizes, units, volumes)",
        ),
        (
            lambda raw: unit(raw, "api").update(name="api"),
            "units[2].name is not a field of units[2] (allowed: a unit's keys: backup, command",
        ),
    ],
    ids=[
        "kind-beside-version",
        "version-beside-kind",
        "kind-type",
        "version-type",
        "annotation-type",
        "required-word",
        "mount-path-type",
        "top-level-key",
        "unit-key",
    ],
)
def test_a_refusal_names_what_its_field_allows(change, expected) -> None:
    raw = copy.deepcopy(seed())
    change(raw)
    assert expected in _messages(raw)


def test_a_required_word_names_the_words_it_may_be() -> None:
    raw = seed()
    raw["rollback"] = {}
    strategies = read({**seed(), "rollback": {"strategy": "?"}}, published_table())[1][0].message
    allowed = strategies.split("(allowed: ")[1]
    assert f"rollback.strategy is required (allowed: {allowed}" in _messages(raw)


def test_the_generator_s_words_are_top_level_keys_only_where_build_is_generated() -> None:
    raw = _generated()
    raw["colour"] = "blue"
    assert "the top-level keys: build, compose, externalDatabase, generator, rollback" in _messages(raw)


def test_a_backup_without_stateful_names_the_flag_it_needs() -> None:
    raw = seed()
    unit(raw, "db").pop("stateful")
    assert "units[0].stateful is required beside backup (allowed: true - a backup policy sits " in (
        _messages(raw)
    )


def test_too_many_entries_names_the_cap() -> None:
    raw = _generated()
    raw["generator"] = {"systemPackages": [f"pkg{index}" for index in range(65)]}
    assert "generator.systemPackages has 65 items (allowed: at most 64 entries)" in _messages(raw)


def test_a_recipe_key_that_is_no_unit_id_names_the_web_units() -> None:
    """The schema refuses the key's form before any reader asks which unit it names; the
    message names what a key may be all the same: a declared web unit's id."""
    raw = _generated()
    raw["generator"] = {"recipes": {"-web": "static-site"}}
    assert (
        "generator.recipes.-web is not a field of generator.recipes (allowed: a declared web "
        "unit's id: web)"
    ) in _messages(raw)
    raw["generator"] = {"recipes": {"public site": "static-site"}}
    assert 'generator.recipes["public site"] is not a field of generator.recipes' in _messages(raw)


# --- the helpers at their edges --------------------------------------------------------


def test_the_helpers_read_paths_and_kinds_at_their_edges() -> None:
    assert [_words.json_kind(value) for value in ([], {}, True, "x", None, 1.5)] == [
        "an array",
        "an object",
        "a boolean",
        "a string",
        "null",
        "a number",
    ]
    assert _words.steps('units[0]["a b"].c') == ["units", 0, "a b", "c"]
    assert _words.shape("sizes.small.cpu") == "sizes.*.cpu"
    assert _words.lookup({"units": [{"id": "api"}]}, "units[0].id") == "api"
    assert _words.lookup({"units": "none"}, "units[0].id") is None
    assert _words.lookup({"units": []}, "units[3]") is None
    assert _words.version_allowed("mysql", {"postgres": ("17",)}) == (
        "the datastore version, declared with its kind"
    )
    assert _words.web_units({"units": "none"}) == "none"
    assert _words.web_units([]) == "none"
    assert _words.or_join([]) == "" and _words.or_join([1]) == "1"
    assert _words.or_join(["a", True, "c"]) == "a, true or c"


def test_a_problem_with_no_words_of_its_own_keeps_its_detail() -> None:
    problem = Problem("x.y", "has 1 item(s) (allowed: at least 2)", "minItems", (2,))
    assert _words.say(problem, {}, {}) == "x.y has 1 item(s) (allowed: at least 2)"
    problem = Problem("", "is something else", "unknown", ())
    assert _words.say(problem, {}, {}) == "deployment.json is something else"
