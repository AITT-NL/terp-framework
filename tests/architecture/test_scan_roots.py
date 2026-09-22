"""Gate for the harness's scanned roots: several roots, per-root rules, one budget.

``assert_app_clean`` took one root, so the only code an application could hold to the
eighty rules was the package ``create_app`` mounts. A repository with a second
deployable — a worker, a publisher, a CLI, a sidecar — had no way to say so, and the
component that most often holds live credentials, assembles SQL as text and speaks to
the network is the component that is not a module (ADR 0141).

These tests pin the three properties that make the seam worth having: a companion root
is scanned *at all*; it is scanned with the rules that are about the code and not with
the ones that are properties of being a mounted application; and its opt-out markers
land in the *same* escape-hatch budget, so an exception cannot be moved out from under
its count.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from terp.arch import (
    APP_ROOT_ONLY,
    ArchDeclarationError,
    EVERY_ROOT,
    RULE_ROOT_KINDS,
    RootKind,
    ScanRoot,
    assert_app_clean,
    check_app,
    check_escape_hatch_budget,
    declared_roots,
    root_kinds_for,
    ungoverned_marker_violations,
)
from terp.arch.rules import _ALL_RULES

# A worker's real shape: credentials from the environment, SQL built as text, an HTTP
# client, and a route-looking function that is not a route. Each line is a violation of
# a rule that travels, except the last, which is a violation of nothing.
_COMPANION_SOURCE = """\
import httpx
from sqlalchemy import text

API_PASSWORD = "hunter2"


def load(conn, table):
    return conn.execute(text(f"SELECT * FROM {table}"))


def push(payload):
    return httpx.post("https://example.invalid/ingest", json=payload)
"""

# The same file, plus the shapes that only mean something inside a mounted app: a
# router with no response model, on a module with no policy.
_APP_CONTRACT_SOURCE = """\
from fastapi import APIRouter

router = APIRouter()


@router.get("/items")
def list_items():
    return []
"""


def _write(root: pathlib.Path, rel: str, source: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def _rules(violations: list) -> set[str]:
    return {violation.rule for violation in violations}


def _repo(tmp_path: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    """A minimal two-deployable repository: a clean ``app/`` and a companion."""
    app = tmp_path / "app"
    _write(app, "modules/notes/service.py", "# clean\n")
    worker = tmp_path / "worker"
    _write(worker, "job.py", _COMPANION_SOURCE)
    return app, worker


def _companion(path: pathlib.Path) -> ScanRoot:
    return ScanRoot(path, package=path.name, kind=RootKind.COMPANION)


# --------------------------------------------------------------------------- #
# the classification is complete, and it did not quietly narrow ADR 0136
# --------------------------------------------------------------------------- #
def test_every_rule_declares_the_root_kinds_it_is_evaluated_over() -> None:
    # The drift guard for the classification, mirroring GUIDE_TOPIC_BY_RULE's: a rule
    # added without a RULE_ROOT_KINDS entry would fall back to EVERY_ROOT and start
    # firing on companion roots the author never considered. Fail here, in the repo
    # that owns the rule, rather than in a consumer's gate.
    registered = {rule.__name__.removeprefix("check_") for rule in _ALL_RULES}
    governance = {"escape_hatch_budget", "ungoverned_escape_hatch"}
    assert registered <= set(RULE_ROOT_KINDS), (
        "every rule must declare its root kinds in RULE_ROOT_KINDS; unclassified: "
        f"{sorted(registered - set(RULE_ROOT_KINDS))}"
    )
    stray = set(RULE_ROOT_KINDS) - registered - governance
    assert not stray, f"RULE_ROOT_KINDS names rules that no longer exist: {sorted(stray)}"
    assert all(kinds in (EVERY_ROOT, APP_ROOT_ONLY) for kinds in RULE_ROOT_KINDS.values()), (
        "a rule is evaluated over every root or over app roots only; a third "
        "applicability needs a decision, not a set literal"
    )


def test_the_security_rules_widened_by_adr_0136_still_reach_every_root() -> None:
    # ADR 0136 widened these four past `app/modules/` after they had spent their whole
    # lives scanning an empty file set. Root kinds are a second dimension and this is
    # where the first one could be undone without looking like it: classifying any of
    # them APP_ROOT_ONLY would re-exempt exactly the sibling package 0136's Context
    # names as where a raw client and a bootstrap credential actually live.
    for rule in (
        "no_hardcoded_credentials",
        "no_dynamic_sql",
        "no_raw_outbound_http",
        "no_manual_table_schema",
    ):
        assert root_kinds_for(rule) == EVERY_ROOT, (
            f"{rule} is one of the four ADR 0136 widened; it must reach a companion root"
        )


def test_an_unclassified_rule_falls_back_to_every_root() -> None:
    # The polarity of the fallback is the decision: silent under-enforcement is the
    # failure this seam exists to refuse, so a rule a consumer's pinned classification
    # has never heard of runs everywhere rather than nowhere.
    assert root_kinds_for("a_rule_from_a_newer_harness") == EVERY_ROOT


# --------------------------------------------------------------------------- #
# a companion root is scanned, and scanned with the right rules
# --------------------------------------------------------------------------- #
def test_a_companion_root_is_held_to_the_rules_about_the_code(tmp_path: pathlib.Path) -> None:
    app, worker = _repo(tmp_path)
    found = check_app(app, _companion(worker))
    assert _rules(found) >= {"no_hardcoded_credentials", "no_dynamic_sql", "no_raw_outbound_http"}
    assert all(violation.path.startswith("worker") for violation in found), (
        "the app root is clean; every violation here comes from the companion"
    )


def test_a_companion_root_is_not_scanned_unless_it_is_passed(tmp_path: pathlib.Path) -> None:
    # The half that would make the test above pass for the wrong reason: if the
    # companion were reached by some other means, dropping it from the call would not
    # change the verdict. It does.
    app, worker = _repo(tmp_path)
    assert check_app(app) == []


def test_a_companion_root_is_not_held_to_the_mounted_app_contract(tmp_path: pathlib.Path) -> None:
    app, worker = _repo(tmp_path)
    _write(worker, "http.py", _APP_CONTRACT_SOURCE)
    companion = _rules(check_app(_companion(worker)))
    assert "routes_declare_response_model" not in companion
    assert "modules_declare_policy" not in companion

    # And the same bytes under an app root do fire, so the exemption is the root kind
    # rather than a rule that cannot see the file.
    as_app = _rules(check_app(ScanRoot(worker, package="worker")))
    assert "routes_declare_response_model" in as_app


def test_a_bare_path_is_still_an_app_root(tmp_path: pathlib.Path) -> None:
    # Backwards compatibility, stated as a property rather than assumed: every existing
    # call site passes a bare path and means "scan this as the app", so a bare path must
    # keep being held to every rule.
    app = tmp_path / "app"
    _write(app, "http.py", _APP_CONTRACT_SOURCE)
    assert "routes_declare_response_model" in _rules(check_app(app))
    assert "routes_declare_response_model" in _rules(check_app(str(app)))


def test_a_missing_companion_root_is_refused(tmp_path: pathlib.Path) -> None:
    # Named by kind, because "app root not found" over a worker directory sends the
    # reader to look at the wrong half of a two-root call.
    app, _worker = _repo(tmp_path)
    with pytest.raises(NotADirectoryError, match="companion root not found"):
        check_app(app, _companion(tmp_path / "nope"))
    with pytest.raises(NotADirectoryError, match="app root not found"):
        check_app(tmp_path / "nope")


# --------------------------------------------------------------------------- #
# one budget, shared
# --------------------------------------------------------------------------- #
def test_a_companion_marker_counts_against_the_apps_one_budget(tmp_path: pathlib.Path) -> None:
    # The property that makes a single budget file mean something: an exception cannot
    # be moved from the app into a sibling package to escape its count.
    app, worker = _repo(tmp_path)
    _write(
        app,
        "modules/notes/service.py",
        "from terp.core._internal.engine import get_engine  # arch-allow-no-internal-imports: app\n",
    )
    _write(
        worker,
        "job.py",
        "from terp.core._internal.engine import get_engine  # arch-allow-no-internal-imports: worker\n",
    )
    budget = tmp_path / "budget.json"

    budget.write_text(json.dumps({"arch-allow-no-internal-imports": 2}), encoding="utf-8")
    assert check_escape_hatch_budget(app, _companion(worker), budget_path=budget) == []

    # Counting only the app root would make this pass at 1, which is the whole bug.
    budget.write_text(json.dumps({"arch-allow-no-internal-imports": 1}), encoding="utf-8")
    drift = check_escape_hatch_budget(app, _companion(worker), budget_path=budget)
    assert [violation.rule for violation in drift] == ["escape_hatch_budget"]
    assert "rose to 2" in drift[0].message


def test_a_marker_naming_a_rule_its_root_never_runs_is_refused(tmp_path: pathlib.Path) -> None:
    # An opt-out that opts out of nothing is worse than no opt-out: it sits in the
    # budget reading like a governed exception while suppressing nothing at all, which
    # is the same false assurance a scoped-out rule produces.
    app, worker = _repo(tmp_path)
    _write(worker, "job.py", "x = 1  # arch-allow-list-routes-paginate: not a route anywhere\n")
    budget = tmp_path / "budget.json"
    budget.write_text(json.dumps({"arch-allow-list-routes-paginate": 1}), encoding="utf-8")
    found = check_escape_hatch_budget(app, _companion(worker), budget_path=budget)
    assert [violation.line for violation in found] == [1]
    assert "suppresses nothing" in found[0].message

    # The same marker on an app root is an ordinary (if unused) opt-out, because there
    # the rule does run — so the refusal is about applicability, not about the token.
    _write(app, "modules/notes/router.py", "x = 1  # arch-allow-list-routes-paginate: fine\n")
    _write(worker, "job.py", "x = 1\n")
    budget.write_text(json.dumps({"arch-allow-list-routes-paginate": 1}), encoding="utf-8")
    assert check_escape_hatch_budget(app, _companion(worker), budget_path=budget) == []


def test_an_ungoverned_marker_in_a_companion_fails_closed(tmp_path: pathlib.Path) -> None:
    app, worker = _repo(tmp_path)
    _write(worker, "job.py", "x = 1  # arch-allow-no-print: because\n")
    with pytest.raises(AssertionError, match="no budget_path"):
        assert_app_clean(app, _companion(worker))
    assert [v.path for v in ungoverned_marker_violations(app, _companion(worker))] == [
        str(pathlib.Path("worker/job.py"))
    ]


def test_assert_app_clean_reports_every_root_in_one_failure(tmp_path: pathlib.Path) -> None:
    app, worker = _repo(tmp_path)
    _write(app, "http.py", _APP_CONTRACT_SOURCE)
    budget = tmp_path / "budget.json"
    budget.write_text(json.dumps({}), encoding="utf-8")
    with pytest.raises(AssertionError) as excinfo:
        assert_app_clean(app, _companion(worker), budget_path=budget)
    message = str(excinfo.value)
    assert "routes_declare_response_model" in message  # from app/
    assert "no_raw_outbound_http" in message  # from worker/


# --------------------------------------------------------------------------- #
# one declaration, read by both entry points
# --------------------------------------------------------------------------- #
def _declaring_repo(tmp_path: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    app, worker = _repo(tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        '[tool.terp.arch]\ncompanions = ["worker"]\n', encoding="utf-8"
    )
    return app, worker


def test_a_project_declares_its_companions_once(tmp_path: pathlib.Path) -> None:
    app, worker = _declaring_repo(tmp_path)
    declared = declared_roots(tmp_path)
    assert [root.package for root in declared] == ["worker"]
    assert [root.kind for root in declared] == [RootKind.COMPANION]
    assert declared[0].path.resolve() == worker.resolve()
    # And the declaration is what the gate scans, not merely what it lists.
    assert _rules(check_app(app, *declared)) >= {"no_raw_outbound_http"}


def test_no_declaration_is_the_ordinary_case(tmp_path: pathlib.Path) -> None:
    _repo(tmp_path)  # no pyproject.toml at all
    assert declared_roots(tmp_path) == ()
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    assert declared_roots(tmp_path) == ()


def test_a_declared_root_that_does_not_exist_is_refused(tmp_path: pathlib.Path) -> None:
    # The failure this refuses is the quiet one: a typo'd directory scans no files, so
    # every rule returns [] and the gate reports clean over a package nobody checked.
    _repo(tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        '[tool.terp.arch]\ncompanions = ["wroker"]\n', encoding="utf-8"
    )
    with pytest.raises(ArchDeclarationError, match="is not a directory"):
        declared_roots(tmp_path)


def test_an_unknown_key_in_the_declaration_is_refused(tmp_path: pathlib.Path) -> None:
    _repo(tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        '[tool.terp.arch]\ncompanion = ["worker"]\n', encoding="utf-8"
    )
    with pytest.raises(ArchDeclarationError, match="unknown key"):
        declared_roots(tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        '[tool.terp.arch]\ncompanions = "worker"\n', encoding="utf-8"
    )
    with pytest.raises(ArchDeclarationError, match="list of directory names"):
        declared_roots(tmp_path)


def test_the_shared_budget_is_why_the_declaration_has_to_be_read_without_a_flag(
    tmp_path: pathlib.Path,
) -> None:
    # The scenario that makes one declaration necessary rather than nice. `terp verify`
    # runs a fixed `terp check` command the app cannot add flags to. If that run did not
    # see the companion, the companion's marker would be counted as *absent*, the
    # ratchet would read it as a win to lock in, and an app that adopted companion roots
    # in its pytest gate would fail its own verify profile for having done so.
    app, worker = _declaring_repo(tmp_path)
    _write(worker, "job.py", "print('x')  # arch-allow-no-print: a CLI prints\n")
    budget = tmp_path / "budget.json"
    budget.write_text(json.dumps({"arch-allow-no-print": 1}), encoding="utf-8")

    assert check_app(app, *declared_roots(tmp_path), budget_path=budget) == []

    # Scanning the app alone against the same shared budget is the failure above.
    drift = check_app(app, budget_path=budget)
    assert [violation.rule for violation in drift] == ["escape_hatch_budget"]
    assert "dropped to 0" in drift[0].message


def test_a_declared_app_package_is_held_to_every_rule(tmp_path: pathlib.Path) -> None:
    # The case that reaches every app rather than only the ones with a worker: the
    # scaffolded shape has always had a second Python package beside `app/`, and
    # `assert_app_clean("app", ...)` scanned one of them. `app_packages` is the other
    # half of the declaration, and it is NOT a companion — a control plane holds the
    # app's permission, operation, event and job declarations, so it is held to the app
    # contract in full.
    app, _worker = _repo(tmp_path)
    plane = tmp_path / "control_plane"
    _write(plane, "operations.py", _APP_CONTRACT_SOURCE)
    (tmp_path / "pyproject.toml").write_text(
        '[tool.terp.arch]\napp_packages = ["control_plane"]\n', encoding="utf-8"
    )
    declared = declared_roots(tmp_path)
    assert [(root.package, root.kind) for root in declared] == [
        ("control_plane", RootKind.APP)
    ]
    # An app-contract rule that a companion root would never run does run here.
    assert "routes_declare_response_model" in _rules(check_app(app, *declared))


def test_the_declaration_orders_app_packages_before_companions(tmp_path: pathlib.Path) -> None:
    app, _worker = _repo(tmp_path)
    (tmp_path / "control_plane").mkdir()
    (tmp_path / "pyproject.toml").write_text(
        '[tool.terp.arch]\ncompanions = ["worker"]\napp_packages = ["control_plane"]\n',
        encoding="utf-8",
    )
    # Declaration order in the file is not the scan order; the kinds are. More of the
    # application first, then what merely ships beside it — so a failure listing reads
    # outward from the app rather than in whatever order the TOML happened to be typed.
    assert [root.package for root in declared_roots(tmp_path)] == ["control_plane", "worker"]


def test_an_unreadable_manifest_is_refused_rather_than_ignored(tmp_path: pathlib.Path) -> None:
    # A manifest that will not parse is the one case where "no declaration" and "a
    # declaration nobody could read" look the same from the outside, and treating them
    # alike would silently narrow the scan to the app package. Say so instead.
    _repo(tmp_path)
    (tmp_path / "pyproject.toml").write_text('[tool.terp.arch\nx = 1\n', encoding="utf-8")
    with pytest.raises(ArchDeclarationError, match="unreadable"):
        declared_roots(tmp_path)


def test_a_declaration_that_is_not_a_table_is_refused(tmp_path: pathlib.Path) -> None:
    _repo(tmp_path)
    (tmp_path / "pyproject.toml").write_text('[tool.terp]\narch = "worker"\n', encoding="utf-8")
    with pytest.raises(ArchDeclarationError, match="not a table"):
        declared_roots(tmp_path)
