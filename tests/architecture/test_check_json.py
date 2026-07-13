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
    assert violation["fix"] == "terp guide policy"


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
    assert ungoverned["fix"] == "terp guide rules"
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
    assert "terp guide policy" in fixes


# --------------------------------------------------------------------------- #
# prose surfaces also carry the recipe pointer
# --------------------------------------------------------------------------- #
def test_assert_app_clean_listing_points_at_the_fix_recipe(tmp_path: pathlib.Path) -> None:
    app = _violating_app(tmp_path)
    with pytest.raises(AssertionError, match=r"architecture violation") as excinfo:
        assert_app_clean(app)
    assert "(fix recipe: terp guide policy)" in str(excinfo.value)
