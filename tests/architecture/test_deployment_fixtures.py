"""The reference reader runs the shared deployment fixtures (ADR 0184), against this corpus.

``deployment-declaration.fixtures.json`` (in the terp-spec contracts package) names, for
every violation case of the three deployment rules, the field the refusal is about and the
values it allows -- so "rejected with the field and the allowed values" is checked rather
than hoped for -- and describes the path escapes a corpus case cannot carry (a symbolic
link, a work tree) as trees a reader's test builds. Every reader runs the same ones.

The corpus those refusals name lives here (ADR 0203), so the checks that hold the two to
each other live here too: one fixture per violation case and one case per fixture, and the
shape the corpus keeps so every reader can judge it (the never-red cases each rule keeps,
truth and render cases that the readable rule passes, a digest-pinned table beside a case
that names a kind or a package). terp-spec held these against its own copy of the corpus
until 0.44.0.

The fixtures ship from the spec release ``SPEC_RELEASE`` names. Until that release is
pinned these tests assert that the pinned spec honestly has none, so the day the pin
moves they start running instead of skipping past it.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import shutil

import pytest
import terp_spec

import terp.arch as arch
from terp.arch.deployment import SPEC_RELEASE
from tests.architecture.rule_layout import corpus_dir

_FIXTURES = terp_spec.spec_dir() / "deployment-declaration.fixtures.json"
_CORPUS = corpus_dir("backend")
_READABLE = "backend/deployment_declaration_is_readable"
_TRUTH = "backend/deployment_declaration_tells_the_truth"
_RENDER = "backend/deployment_generated_files_match_their_render"
_RULES = (_READABLE, _TRUTH, _RENDER)
_DIGEST = r"[a-z0-9./-]+@sha256:[0-9a-f]{64}"


def _fixtures() -> dict | None:
    """The pinned spec's fixtures, or ``None`` while it is a release from before them."""
    released = tuple(int(part) for part in terp_spec.spec_version().split("."))
    if released < tuple(int(part) for part in SPEC_RELEASE.split(".")):
        assert not _FIXTURES.is_file(), f"terp-spec {terp_spec.spec_version()} already ships them"
        return None
    assert _FIXTURES.is_file(), f"terp-spec {terp_spec.spec_version()} ships no fixtures"
    return json.loads(_FIXTURES.read_text(encoding="utf-8"))


def _needle(field: str) -> str:
    """How a reader's message names a fixture's field: ``$`` is the file itself."""
    return "deployment.json" if field == "$" else field.removeprefix("$.")


def _run(rule: str, project: pathlib.Path) -> list:
    return getattr(arch, f"check_{rule.removeprefix('backend/')}")(
        project, datastore_table=project / "datastore-table.json"
    )


def test_every_violation_case_is_refused_at_the_field_its_fixture_names(tmp_path) -> None:
    fixtures = _fixtures()
    if fixtures is None:
        return
    checked = 0
    for rule, cases in fixtures["refusals"].items():
        for case, expected in cases.items():
            project = tmp_path / rule.replace("/", "-") / case / "app"
            shutil.copytree(_CORPUS / rule.removeprefix("backend/") / case, project)
            violations = _run(rule, project)
            messages = [violation.message for violation in violations]
            assert any(_needle(expected["field"]) in message for message in messages), (
                f"{rule}/{case}: refused, but no message names {expected['field']}: {messages}"
            )
            if "in" in expected:
                assert any(violation.path == expected["in"] for violation in violations), (
                    f"{rule}/{case}: the refusal belongs to {expected['in']}"
                )
            checked += 1
    assert checked >= 50, "the fixtures name every violation case of the three rules"


def _cases(rule: str, prefix: str = "") -> list[pathlib.Path]:
    directory = _CORPUS / rule.removeprefix("backend/")
    return sorted(case for case in directory.iterdir() if case.is_dir() and case.name.startswith(prefix))


def _declaration(case: pathlib.Path) -> object:
    """The case's ``deployment.json`` as JSON, ``None`` when absent or not JSON."""
    file = case / "deployment.json"
    if not file.is_file():
        return None
    try:
        return json.loads(file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _readable(case: pathlib.Path, tmp_path: pathlib.Path) -> list:
    project = tmp_path / "readable" / case.parent.name / case.name / "app"
    shutil.copytree(case, project)
    return _run(_READABLE, project)


def test_every_violation_case_has_exactly_one_fixture() -> None:
    """A violation case the fixtures do not name is one no other reader is held to; a
    fixture naming no case is a refusal nothing exercises. Both directions, per rule."""
    fixtures = _fixtures()
    if fixtures is None:
        return
    assert set(fixtures["refusals"]) == set(_RULES)
    for rule in _RULES:
        cases = {case.name for case in _cases(rule, "violation-")}
        named = set(fixtures["refusals"][rule])
        assert cases == named, (
            f"{rule}: cases without a fixture {sorted(cases - named)}, "
            f"fixtures without a case {sorted(named - cases)}"
        )
    assert len(_cases(_READABLE, "violation-")) >= 20, "twenty broken declarations, at least"


def test_each_rule_keeps_the_cases_that_must_never_be_red() -> None:
    """An absent file and the opted-out state with a reason are never red, and every rule
    has a compliant case that says so."""
    for rule in _RULES:
        compliant = _cases(rule, "compliant-")
        assert any(not (case / "deployment.json").exists() for case in compliant), (
            f"{rule}: an absent file is never red, and a compliant case says so"
        )
        assert any(
            isinstance(document, dict) and document.get("unmanaged") is True
            for document in map(_declaration, compliant)
        ), f"{rule}: the opted-out state is never red, and a compliant case says so"


def test_every_truth_case_is_readable_so_it_tests_only_the_truth(tmp_path) -> None:
    """A reader stops at the first rule a declaration breaks, so a truth case that is also
    unreadable proves nothing about the truth check."""
    for case in _cases(_TRUTH):
        assert _readable(case, tmp_path) == [], f"{case.name}: the readable rule refuses it"


def test_the_render_corpus_holds_only_what_every_reader_can_judge(tmp_path) -> None:
    """No case carries the expected render: the generator's bytes move with every release's
    base-image digests. So every violation is a readable generated declaration, red whatever
    the render is, and the compliant cases sample each of the four states the rule is silent
    in."""
    for case in _cases(_RENDER, "violation-"):
        document = _declaration(case)
        assert isinstance(document, dict) and document.get("build") == "generated", case.name
        assert _readable(case, tmp_path) == [], f"{case.name}: the readable rule would stop first"
    silent: set[str] = set()
    for case in _cases(_RENDER, "compliant-"):
        document = _declaration(case)
        if not (case / "deployment.json").is_file():
            silent.add("undeclared")
        elif _readable(case, tmp_path):
            silent.add("unreadable")
        elif document.get("unmanaged") is True:
            silent.add("opted out")
        else:
            assert document.get("build") == "own", f"{case.name}: a generated case is judged"
            silent.add("own")
    assert silent == {"undeclared", "unreadable", "opted out", "own"}, sorted(silent)


def test_a_case_that_names_a_kind_or_a_package_ships_its_table() -> None:
    """Which datastore kinds, versions, digests and system packages exist is per framework
    release, so a case that names one carries the table it resolves against."""
    for rule in _RULES:
        for case in _cases(rule):
            document = _declaration(case)
            if not isinstance(document, dict):
                continue
            units = document.get("units") if isinstance(document.get("units"), list) else []
            if any(isinstance(unit, dict) and "kind" in unit for unit in units):
                table = json.loads((case / "datastore-table.json").read_text(encoding="utf-8"))
                assert set(table) == {"kinds"}, f"{rule}/{case.name}"
                for kind, entry in table["kinds"].items():
                    assert set(entry) == {"role", "versions"}, f"{rule}/{case.name}: {kind}"
                    assert entry["role"] in {"database", "store"}, f"{rule}/{case.name}: {kind}"
                    for version, image in entry["versions"].items():
                        assert re.fullmatch(_DIGEST, image), f"{rule}/{case.name}: {kind} {version}"
            generator = document.get("generator")
            if isinstance(generator, dict) and generator.get("systemPackages"):
                table = json.loads((case / "system-package-table.json").read_text(encoding="utf-8"))
                assert set(table) == {"packages"} and isinstance(table["packages"], dict), case.name


def test_the_tree_fixtures_a_corpus_case_cannot_carry(tmp_path) -> None:
    fixtures = _fixtures()
    if fixtures is None:
        return
    for tree in fixtures["trees"]:
        root = tmp_path / tree["id"]
        for name, text in tree["files"].items():
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_text(text, encoding="utf-8")
        try:
            for link, destination in tree["links"].items():
                os.symlink(destination, root / link, target_is_directory=True)
        except OSError:  # pragma: no cover - a Windows account without the link privilege
            continue
        if "workTree" in tree:
            (root / tree["workTree"] / ".git").mkdir(parents=True, exist_ok=True)
        violations = _run(tree["rule"], root / tree["projectRoot"])
        if tree["expect"] == "compliant":
            assert violations == [], f"{tree['id']}: {violations}"
        else:
            assert any(_needle(tree["field"]) in violation.message for violation in violations), (
                f"{tree['id']}: {[violation.message for violation in violations]}"
            )


@pytest.mark.parametrize("rule", sorted(arch.PROJECT_ROOT_RULES))
def test_a_project_rule_s_entry_point_is_the_one_the_catalog_names(rule) -> None:
    """The corpus runner reaches these through ``check_<rule>``."""
    assert callable(getattr(arch, f"check_{rule}"))
