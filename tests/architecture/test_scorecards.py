"""The backend scorecard emitter is held to the certification contract.

``tools/emit_backend_scorecard.py`` publishes the terp-arch scorecard
(``scorecard.schema.json``): the artifact that makes "certified against spec
X.Y.Z" verifiable. These assertions run the real emitter and hold its output
to the schema shape, full corpus-covered catalog coverage, a green harness,
and the residual-subset rule — plus the validator's own refusals, so a broken
scorecard can never be written quietly.
"""

from __future__ import annotations

import copy
import json
import pathlib
import re
import subprocess
import sys

import pytest
import terp_spec

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_TOOL = _REPO_ROOT / "tools" / "emit_backend_scorecard.py"
_SPEC = terp_spec.spec_dir()

sys.path.insert(0, str(_REPO_ROOT / "tools"))

from emit_backend_scorecard import build_scorecard, validate_scorecard  # noqa: E402


def _schema() -> dict:
    return json.loads((_SPEC / "scorecard.schema.json").read_text(encoding="utf-8"))


def test_the_scorecard_claims_the_whole_catalog_green_and_schema_shaped() -> None:
    scorecard = build_scorecard()
    assert validate_scorecard(scorecard) == []

    schema = _schema()
    assert set(schema["required"]) <= set(scorecard)
    assert set(scorecard) <= set(schema["properties"])
    assert scorecard["spec_version"] == terp_spec.spec_version()
    assert scorecard["checker"]["tool"] == "terp-arch"
    assert re.fullmatch(r"\d+\.\d+\.\d+|0", str(scorecard["checker"]["version"]))

    corpus_covered = {
        json.loads(path.read_text(encoding="utf-8"))["id"]
        for path in (_SPEC / "catalog" / "backend").glob("*.json")
        if json.loads(path.read_text(encoding="utf-8"))["corpus"]
    }
    assert {claim["rule"] for claim in scorecard["rules"]} == corpus_covered
    item_properties = set(schema["properties"]["rules"]["items"]["properties"])
    for claim in scorecard["rules"]:
        assert claim["pass"] is True, f"{claim['rule']}: the harness must pass its corpus"
        assert set(claim) <= item_properties

    # The residual claims are exactly the spec's recorded backend residuals —
    # the reference detectors are the ones the ratchet documents.
    residuals = json.loads(
        (_SPEC / "corpus" / "RESIDUALS.json").read_text(encoding="utf-8")
    )["residuals"]
    claimed = {
        claim["rule"]: claim["residuals_claimed"]
        for claim in scorecard["rules"]
        if "residuals_claimed" in claim
    }
    expected = {
        rule: entries for rule, entries in residuals.items() if rule.startswith("backend/")
    }
    assert claimed == expected


def test_the_validator_refuses_failing_and_overclaiming_scorecards() -> None:
    scorecard = build_scorecard()
    failing = copy.deepcopy(scorecard)
    failing["rules"][0]["pass"] = False
    assert any("must pass" in problem for problem in validate_scorecard(failing))
    overclaiming = copy.deepcopy(scorecard)
    overclaiming["rules"][0]["residuals_claimed"] = ["a residual the spec never recorded"]
    assert any("unrecorded residual" in p for p in validate_scorecard(overclaiming))
    empty = {**copy.deepcopy(scorecard), "rules": []}
    assert validate_scorecard(empty)


def test_the_cli_writes_a_parseable_scorecard(tmp_path: pathlib.Path) -> None:
    out = tmp_path / "scorecard.json"
    completed = subprocess.run(  # noqa: S603 — fixed argv, no shell
        [sys.executable, str(_TOOL), "--out", str(out)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["checker"]["tool"] == "terp-arch"
    assert written["spec_version"] == terp_spec.spec_version()



# --------------------------------------------------------------------------- #
# The emitter's own branches, in-process (the subprocess test above proves the CLI
# runs; coverage cannot see inside it)
# --------------------------------------------------------------------------- #
import emit_backend_scorecard as emitter  # noqa: E402


def _good_scorecard() -> dict:
    return copy.deepcopy(build_scorecard())


def test_every_validation_problem_is_named() -> None:
    card = _good_scorecard()
    card["spec_version"] = "latest"
    card["checker"] = {"tool": "terp-arch"}
    card["rules"].append({"rule": "Not A Rule", "pass": "yes"})
    problems = validate_scorecard(card)
    assert "spec_version is not a semver string" in problems
    assert "checker must carry tool and version" in problems
    assert "bad rule id: 'Not A Rule'" in problems
    assert "Not A Rule: pass must be a boolean" in problems

    assert "a scorecard without rule claims certifies nothing" in validate_scorecard(
        {**_good_scorecard(), "rules": []}
    )


def test_a_source_checkout_reports_version_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    def not_installed(name: str) -> str:
        raise emitter.importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(emitter.importlib.metadata, "version", not_installed)
    assert build_scorecard()["checker"]["version"] == "0"


def test_a_rule_without_corpus_is_not_claimed(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog = tmp_path / "catalog"
    catalog.mkdir()
    (catalog / "draft_rule.json").write_text(
        json.dumps({"id": "backend/draft_rule", "corpus": False}), encoding="utf-8"
    )
    monkeypatch.setattr(emitter, "_CATALOG", catalog)
    assert build_scorecard()["rules"] == []


def _corpus_with(tmp_path: pathlib.Path, case: str) -> pathlib.Path:
    corpus = tmp_path / "corpus"
    (corpus / "some_rule" / case).mkdir(parents=True)
    (corpus / "some_rule" / "NOTES.md").write_text("not a case", encoding="utf-8")
    return corpus


def test_a_violation_the_rule_misses_fails_the_rule(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(emitter, "_CORPUS", _corpus_with(tmp_path, "violation-01"))
    monkeypatch.setattr(emitter, "_run_rule", lambda rule, root: [])
    assert emitter._rule_passes("some_rule") is False


def test_a_compliant_case_the_rule_reports_fails_the_rule(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Finding:
        rule = "some_rule"

    monkeypatch.setattr(emitter, "_CORPUS", _corpus_with(tmp_path, "compliant-01"))
    monkeypatch.setattr(emitter, "_run_rule", lambda rule, root: [Finding()])
    assert emitter._rule_passes("some_rule") is False


def test_main_writes_the_scorecard_or_names_its_problems(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    card = {"spec_version": "1.2.3", "checker": {"tool": "t", "version": "1"}, "rules": [{}]}
    monkeypatch.setattr(emitter, "build_scorecard", lambda: card)

    monkeypatch.setattr(emitter, "validate_scorecard", lambda scorecard: [])
    monkeypatch.setattr(sys, "argv", ["emit_backend_scorecard.py"])
    assert emitter.main() == 0
    assert json.loads(capsys.readouterr().out) == card

    out = tmp_path / "scorecard.json"
    monkeypatch.setattr(sys, "argv", ["emit_backend_scorecard.py", "--out", str(out)])
    assert emitter.main() == 0
    assert json.loads(out.read_text(encoding="utf-8")) == card
    assert "wrote" in capsys.readouterr().err

    monkeypatch.setattr(emitter, "validate_scorecard", lambda scorecard: ["broken claim"])
    assert emitter.main() == 1
    assert "scorecard: broken claim" in capsys.readouterr().err
