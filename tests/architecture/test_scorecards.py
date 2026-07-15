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
