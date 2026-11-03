"""The reference reader runs the Terp Standard's own deployment fixtures (ADR 0184).

``deployment-declaration.fixtures.json`` names, for every violation case of the two
deployment rules, the field the refusal is about and the values it allows -- so
"rejected with the field and the allowed values" is checked rather than hoped for --
and describes the path escapes a corpus case cannot carry (a symbolic link, a work
tree) as trees a reader's test builds. Every reader runs the same ones.

The fixtures ship from the spec release ``SPEC_RELEASE`` names. Until that release is
pinned these tests assert that the pinned spec honestly has none, so the day the pin
moves they start running instead of skipping past it.
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil

import pytest
import terp_spec

import terp.arch as arch
from terp.arch.deployment import SPEC_RELEASE

_FIXTURES = terp_spec.spec_dir() / "deployment-declaration.fixtures.json"
_CORPUS = terp_spec.spec_dir() / "corpus" / "backend"


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
    assert checked >= 50, "the fixtures name every violation case of both rules"


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
    """The corpus runner and the scorecard reach these through ``check_<rule>``."""
    assert callable(getattr(arch, f"check_{rule}"))
