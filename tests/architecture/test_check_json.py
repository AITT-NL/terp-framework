"""``terp check --format json`` — the structured gate surface (agent ergonomics).

Every violation carries its own fix: the rule, the exact file/line, the teaching
message, the ``terp guide`` topic with the compliant recipe, and a copy-pasteable
``fix`` command. This is the machine-readable seam a driving tool (the Studio's
gate loop, an editor, a CI annotator) consumes instead of parsing a prose wall —
and the ``assert_app_clean`` prose listing now points at the same recipes.
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

# terp-cli is not pip-installed in the dev venv; inject its src (as the other CLI tests do).
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CLI_SRC = _REPO_ROOT / "packages" / "backend" / "cli" / "src"
sys.path.insert(0, str(_CLI_SRC))

from terp.arch import (  # noqa: E402  (import after sys.path setup)
    GUIDE_TOPIC_BY_RULE,
    assert_app_clean,
    guide_topic_for,
    ungoverned_marker_violations,
)
from terp.arch.rules import _ALL_RULES  # noqa: E402
from terp.cli import check_report, guide_topics, main  # noqa: E402

_EXAMPLE_ROOT = _REPO_ROOT / "apps" / "example"


def _write(app: pathlib.Path, rel: str, content: str) -> None:
    path = app / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _violating_app(tmp_path: pathlib.Path) -> pathlib.Path:
    app = tmp_path / "app"
    _write(app, "modules/billing/module.py", "module = ModuleSpec(name='billing', router=router)\n")
    return app


# --------------------------------------------------------------------------- #
# the rule -> guide-topic registry (every violation knows its fix recipe)
# --------------------------------------------------------------------------- #
def test_every_rule_has_a_guide_topic() -> None:
    # Completeness: a new rule must declare which recipe teaches its fix; the
    # unmapped fallback ("rules") never becomes the silent norm.
    unmapped = {
        rule.__name__.removeprefix("check_")
        for rule in _ALL_RULES
        if rule.__name__.removeprefix("check_") not in GUIDE_TOPIC_BY_RULE
    }
    assert unmapped == set(), f"map each rule to its `terp guide` topic: {sorted(unmapped)}"


def test_every_mapped_topic_is_a_real_guide_topic() -> None:
    # The other direction of parity: a mapping must point at a recipe that exists,
    # so `fix: terp guide <topic>` is always a runnable command.
    topics = set(guide_topics())
    dangling = {rule: topic for rule, topic in GUIDE_TOPIC_BY_RULE.items() if topic not in topics}
    assert dangling == {}, f"guide-topic mapping points at missing topics: {dangling}"


def test_guide_topic_for_falls_back_to_rules() -> None:
    assert guide_topic_for("modules_declare_policy") == "policy"
    # An unmapped rule never crashes a renderer — it points at the generated topic.
    assert guide_topic_for("some_future_rule") == "rules"


# --------------------------------------------------------------------------- #
# check_report — the structured body
# --------------------------------------------------------------------------- #
def test_check_report_is_clean_on_the_example_app() -> None:
    report = check_report(
        str(_EXAMPLE_ROOT), budget_path=str(_EXAMPLE_ROOT / "escape-hatch-budget.json")
    )
    assert report == {
        "ok": True,
        "rules": sorted(GUIDE_TOPIC_BY_RULE),
        "violation_count": 0,
        "violations": [],
    }


def test_check_report_carries_the_evaluated_rule_inventory(tmp_path: pathlib.Path) -> None:
    # The report names every rule the run actually held the app to, pass or fail —
    # the seam a spec-matrix consumer joins on, so "pass" can never be claimed for
    # a rule this toolchain never ran. Without a budget the ratchet never ran, so
    # `escape_hatch_budget` stays OUT of the inventory (only the ungoverned-marker
    # condition was enforced); with a budget the ratchet ran and subsumes it.
    app = _violating_app(tmp_path)
    unbudgeted = check_report(str(app))
    assert unbudgeted["rules"] == sorted(set(GUIDE_TOPIC_BY_RULE) - {"escape_hatch_budget"})
    assert "ungoverned_escape_hatch" in unbudgeted["rules"]
    assert "escape_hatch_budget" not in unbudgeted["rules"]
    in_registry = {rule.__name__.removeprefix("check_") for rule in _ALL_RULES}
    assert in_registry <= set(unbudgeted["rules"])
    assert {violation["rule"] for violation in unbudgeted["violations"]} <= set(
        unbudgeted["rules"]
    )
    budget = tmp_path / "budget.json"
    budget.write_text(json.dumps({}), encoding="utf-8")
    budgeted = check_report(str(app), budget_path=str(budget))
    assert budgeted["rules"] == sorted(GUIDE_TOPIC_BY_RULE)


def test_check_report_violation_carries_its_own_fix(tmp_path: pathlib.Path) -> None:
    app = _violating_app(tmp_path)
    report = check_report(str(app))
    assert report["ok"] is False
    assert report["violation_count"] == len(report["violations"]) > 0
    violation = next(
        item for item in report["violations"] if item["rule"] == "modules_declare_policy"
    )
    assert violation["path"].endswith("modules/billing/module.py")
    assert violation["line"] == 1
    assert "policy" in violation["message"]
    assert violation["guide_topic"] == "policy"
    assert violation["fix"] == "terp guide modules_declare_policy"


def test_check_report_surfaces_ungoverned_markers_in_band(tmp_path: pathlib.Path) -> None:
    # The condition assert_app_clean fails closed on (an opt-out marker with no
    # governing budget) is reported as a structured violation, not a crash.
    app = tmp_path / "app"
    _write(
        app,
        "modules/x/service.py",
        "from terp.core._internal import x  # arch-allow-no-internal-imports: legacy\n",
    )
    report = check_report(str(app))
    assert report["ok"] is False
    rules = {violation["rule"] for violation in report["violations"]}
    assert "ungoverned_escape_hatch" in rules
    ungoverned = next(
        violation
        for violation in report["violations"]
        if violation["rule"] == "ungoverned_escape_hatch"
    )
    assert "escape-hatch-budget.json" in ungoverned["message"]
    assert ungoverned["fix"] == "terp guide ungoverned_escape_hatch"
    # With a governing budget the marker is honoured and the condition disappears.
    budget = tmp_path / "budget.json"
    budget.write_text(json.dumps({"arch-allow-no-internal-imports": 1}), encoding="utf-8")
    governed = check_report(str(app), budget_path=str(budget))
    assert governed["ok"] is True


def test_ungoverned_marker_violations_are_sorted_per_line(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    _write(
        app,
        "modules/x/service.py",
        "b = 2  # arch-allow-mutations-emit-audit: two\n"
        "a = 1  # arch-allow-mutations-emit-audit: one\n",
    )
    violations = ungoverned_marker_violations(app)
    assert [violation.line for violation in violations] == [1, 2]
    assert {violation.rule for violation in violations} == {"ungoverned_escape_hatch"}


# --------------------------------------------------------------------------- #
# the CLI surface — `terp check --format json` exit-code semantics
# --------------------------------------------------------------------------- #
def test_cli_check_json_prints_report_and_exits_zero_when_clean(
    capsys: pytest.CaptureFixture[str],
) -> None:
    main(
        [
            "check",
            "--root",
            str(_EXAMPLE_ROOT),
            "--budget",
            str(_EXAMPLE_ROOT / "escape-hatch-budget.json"),
            "--format",
            "json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["rules"] == sorted(GUIDE_TOPIC_BY_RULE)


def test_cli_check_json_exits_nonzero_on_violations(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    app = _violating_app(tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        main(["check", "--root", str(app), "--format", "json"])
    assert excinfo.value.code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    fixes = {violation["fix"] for violation in payload["violations"]}
    assert "terp guide modules_declare_policy" in fixes


# --------------------------------------------------------------------------- #
# prose surfaces also carry the recipe pointer
# --------------------------------------------------------------------------- #
def test_assert_app_clean_listing_points_at_the_fix_recipe(tmp_path: pathlib.Path) -> None:
    app = _violating_app(tmp_path)
    with pytest.raises(AssertionError, match=r"architecture violation") as excinfo:
        assert_app_clean(app)
    assert "(fix recipe: terp guide modules_declare_policy)" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# the check report (`terp check --format check-report`) — the Terp Standard's
# app-check-report.schema.json shape, self-describing and catalog-attributed
# --------------------------------------------------------------------------- #
def _check_report_schema() -> dict:
    import terp_spec

    return json.loads(
        (terp_spec.spec_dir() / "app-check-report.schema.json").read_text(encoding="utf-8")
    )


def test_spec_version_constants_match_the_pinned_spec() -> None:
    # The drift lock for the coupled pin bump: the constants the check reports
    # carry must equal the pinned terp-spec release. Deliberately NOT part of
    # test_spec_catalog.py — the spec repo's certify-against-reference runs that
    # file against CANDIDATE spec versions, which are allowed to be newer; this
    # framework-gate-only test is what forces the constants to move together
    # with the pins.
    import re as _re

    import terp_spec

    from terp.arch import SPEC_VERSION

    assert SPEC_VERSION == terp_spec.spec_version(), (
        "terp.arch.SPEC_VERSION must equal the pinned terp-spec release — bump the "
        "constant together with the [tool.uv.sources] pin"
    )
    spec_js = (
        _REPO_ROOT
        / "packages"
        / "frontend"
        / "eslint-boundaries"
        / "src"
        / "spec.js"
    ).read_text(encoding="utf-8")
    match = _re.search(r'export const SPEC_VERSION = "([^"]+)"', spec_js)
    assert match is not None, "eslint-boundaries/src/spec.js must export SPEC_VERSION"
    assert match.group(1) == terp_spec.spec_version(), (
        "@terpjs/eslint-boundaries SPEC_VERSION must equal the pinned @terp/spec release — "
        "bump the constant together with the package.json pin"
    )


def test_check_report_envelope_is_clean_and_attributed_on_the_example_app() -> None:
    from terp.cli import check_report_envelope

    envelope = check_report_envelope(
        str(_EXAMPLE_ROOT), budget_path=str(_EXAMPLE_ROOT / "escape-hatch-budget.json")
    )
    assert envelope["terp_check_report"] == 1
    assert envelope["ok"] is True
    assert envelope["checker"]["tool"] == "terp-arch"
    assert envelope["findings"] == []
    assert envelope["unattributed"] == []
    assert envelope["rules"] == [f"backend/{rule}" for rule in sorted(GUIDE_TOPIC_BY_RULE)]


def test_check_report_envelope_versions_a_source_checkout_as_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A checkout where terp-arch is not an installed distribution (the platform
    # repo itself, a vendored copy) still emits a well-formed checker identity:
    # version "0", never a crash and never an invented number.
    import importlib.metadata

    from terp.cli import check_report_envelope

    def missing(name: str) -> str:
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "version", missing)
    envelope = check_report_envelope(
        str(_EXAMPLE_ROOT), budget_path=str(_EXAMPLE_ROOT / "escape-hatch-budget.json")
    )
    assert envelope["checker"] == {"tool": "terp-arch", "version": "0"}


def test_check_report_envelope_validates_against_the_spec_schema(
    tmp_path: pathlib.Path,
) -> None:
    # Held to app-check-report.schema.json field by field (the same manual
    # discipline test_spec_corpus applies to the finding format), so the emitted
    # document can never drift from the published contract.
    import re as _re

    from terp.cli import check_report_envelope

    schema = _check_report_schema()
    envelope = check_report_envelope(str(_violating_app(tmp_path)))
    assert envelope["ok"] is False

    assert set(schema["required"]) <= set(envelope)
    assert set(envelope) <= set(schema["properties"])
    assert envelope["terp_check_report"] in schema["properties"]["terp_check_report"]["enum"]
    assert _re.fullmatch(
        schema["properties"]["spec_version"]["pattern"].strip("^$"),
        envelope["spec_version"],
    )
    rule_pattern = _re.compile(schema["properties"]["rules"]["items"]["pattern"])
    assert envelope["rules"] and all(rule_pattern.match(rule) for rule in envelope["rules"])

    item = schema["properties"]["findings"]["items"]
    finding_rule_pattern = _re.compile(item["properties"]["rule"]["pattern"])
    assert envelope["findings"], "the violating app must produce findings"
    for finding in envelope["findings"]:
        assert set(item["required"]) <= set(finding)
        assert set(finding) <= set(item["properties"])
        assert finding_rule_pattern.match(finding["rule"])
        assert "\\" not in finding["path"]
        if "line" in finding:
            assert isinstance(finding["line"], int) and finding["line"] >= 1
        assert finding["fix_hint"].startswith("terp guide ")
        assert finding["rule"] in set(envelope["rules"])


def test_cli_check_report_format_exits_by_verdict(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(
        [
            "check",
            "--root",
            str(_EXAMPLE_ROOT),
            "--budget",
            str(_EXAMPLE_ROOT / "escape-hatch-budget.json"),
            "--format",
            "check-report",
        ]
    )
    clean = json.loads(capsys.readouterr().out)
    assert clean["terp_check_report"] == 1 and clean["ok"] is True

    app = _violating_app(tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        main(["check", "--root", str(app), "--format", "check-report"])
    assert excinfo.value.code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert {finding["rule"] for finding in payload["findings"]} >= {
        "backend/modules_declare_policy"
    }
