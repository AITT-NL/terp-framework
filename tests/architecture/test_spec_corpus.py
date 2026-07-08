"""The reference harness is held to the Terp Standard's violation corpus (ADR 0080).

Phase 2 of the standard extraction: ``spec/corpus/backend/<rule>/`` holds
violating and compliant sample app trees per rule — the executable meaning of
the catalog. This test runs the *actual* ``terp.arch`` rule over every case:

* every ``violation-*`` case must produce at least one finding for that rule;
* every ``compliant-*`` case must produce **no** findings for that rule.

The same contract certifies any future checker (another language's rule pack)
against the same corpus — this test simply proves the reference implementation
passes its own standard. The frontend half lives in
``packages/frontend/eslint-boundaries/src/corpus.test.js``.
"""

from __future__ import annotations

import json
import pathlib
import re
import shutil

import pytest
from terp_spec import spec_dir

import terp.arch as arch

_SPEC = spec_dir()
_CATALOG = _SPEC / "catalog" / "backend"
_CORPUS = _SPEC / "corpus" / "backend"


def _run_rule(rule: str, app_root: pathlib.Path) -> list:
    """Run the reference check for *rule* over *app_root*.

    Two rules have bespoke entry points (their catalog entries name the same
    refs): ``escape_hatch_budget`` takes the checked-in budget as an explicit
    input (the corpus case ships it as ``escape-hatch-budget.json`` at the case
    root), and ``ungoverned_escape_hatch`` is projected by
    ``ungoverned_marker_violations`` (the budget-less condition).
    """
    if rule == "escape_hatch_budget":
        return arch.check_escape_hatch_budget(
            app_root, budget_path=app_root / "escape-hatch-budget.json"
        )
    if rule == "ungoverned_escape_hatch":
        return arch.ungoverned_marker_violations(app_root)
    return getattr(arch, f"check_{rule}")(app_root)


def _corpus_cases() -> list[tuple[str, str]]:
    """Every (rule, case-dir-name) pair the backend catalog claims corpus for."""
    cases: list[tuple[str, str]] = []
    for path in sorted(_CATALOG.glob("*.json")):
        entry = json.loads(path.read_text(encoding="utf-8"))
        if not entry["corpus"]:
            continue
        for case in sorted((_CORPUS / path.stem).iterdir()):
            if case.is_dir():
                cases.append((path.stem, case.name))
    return cases


@pytest.mark.parametrize(("rule", "case"), _corpus_cases())
def test_reference_rule_matches_the_corpus(rule: str, case: str, tmp_path: pathlib.Path) -> None:
    app_root = tmp_path / "app"
    shutil.copytree(_CORPUS / rule / case, app_root)
    fired = {violation.rule for violation in _run_rule(rule, app_root)}
    if case.startswith("violation-"):
        assert rule in fired, f"{rule}/{case}: the rule must flag its violation sample"
    else:
        assert rule not in fired, f"{rule}/{case}: the rule must stay silent on compliant code"


# --------------------------------------------------------------------------- #
# findings round-trip: the reference checker's output conforms to the published
# finding format (spec/findings.schema.json), so downstream consumers can trust
# the contract a Level 2 checker is certified against (ADR 0081).
# --------------------------------------------------------------------------- #
def _as_finding(violation: object, app_root: pathlib.Path) -> dict:
    """Render an ``ArchViolation`` in the spec's finding shape (catalog-id attributed).

    ``ArchViolation.path`` is relative to the scanned tree's parent (``app/modules/…``);
    the spec states paths relative to the checked tree's root, forward-slashed. ``line``
    is optional in the spec ("when the checker can locate it") — a whole-tree condition
    such as an escape-hatch budget mismatch carries line 0, so it is omitted there.
    """
    rel = pathlib.PurePath(violation.path).as_posix().removeprefix(f"{app_root.name}/")
    finding = {
        "rule": f"backend/{violation.rule}",
        "path": rel,
        "message": violation.message,
    }
    if violation.line >= 1:
        finding["line"] = violation.line
    return finding


def test_reference_findings_validate_against_the_findings_schema(
    tmp_path: pathlib.Path,
) -> None:
    schema = json.loads(
        (_SPEC / "findings.schema.json").read_text(encoding="utf-8")
    )
    item = schema["items"]
    allowed = set(item["properties"])
    rule_pattern = re.compile(item["properties"]["rule"]["pattern"])

    findings: list[dict] = []
    for rule, case in _corpus_cases():
        if not case.startswith("violation-"):
            continue
        app_root = tmp_path / f"{rule}-{case}" / "app"
        shutil.copytree(_CORPUS / rule / case, app_root)
        findings.extend(_as_finding(violation, app_root) for violation in _run_rule(rule, app_root))

    assert findings, "the violation corpus must produce at least one finding"
    for finding in findings:
        assert set(item["required"]) <= set(finding), f"missing required field: {finding}"
        assert set(finding) <= allowed, f"unexpected field (additionalProperties): {finding}"
        assert rule_pattern.match(finding["rule"]), f"bad rule id: {finding['rule']!r}"
        assert isinstance(finding["path"], str) and "\\" not in finding["path"], (
            f"path must be forward-slash relative: {finding['path']!r}"
        )
        if "line" in finding:
            assert isinstance(finding["line"], int) and finding["line"] >= item["properties"][
                "line"
            ]["minimum"], f"line must be a 1-based integer: {finding}"
        assert isinstance(finding["message"], str) and finding["message"].strip(), (
            f"message must be non-empty: {finding}"
        )
