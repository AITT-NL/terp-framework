"""Every test module that takes ``terp_db_url`` runs in CI's PostgreSQL lane.

The fixture runs a test on SQLite and again on PostgreSQL wherever
``TERP_TEST_POSTGRES_URL`` names a server. Only one job has a server, so a module the
lane does not name runs its PostgreSQL half nowhere. A skip is green, and the module's
claim to cover both dialects reads as true. That happened to the audit activity's
per-day counts in 0.32.0's development: claimed for both, run on one.
"""

from __future__ import annotations

import pathlib
import re

import yaml

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_LANE_STEP = "Run every test that takes terp_db_url against PostgreSQL"


def _lane_command() -> str:
    workflow = yaml.safe_load((_REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    for job in workflow["jobs"].values():
        for step in job.get("steps", ()):
            if step.get("name") == _LANE_STEP:
                assert step["env"]["TERP_REQUIRE_POSTGRES_LANE"] == "1", "a skip in the lane must fail"
                return step["run"]
    raise AssertionError(f"no CI step named {_LANE_STEP!r}")


def _modules_taking_the_fixture() -> set[str]:
    taking = re.compile(r"\bterp_db_url\b")
    return {
        path.relative_to(_REPO_ROOT).as_posix()
        for path in (_REPO_ROOT / "tests").rglob("test_*.py")
        if path.name != pathlib.Path(__file__).name
        and taking.search(path.read_text(encoding="utf-8"))
        # The fixture's own tests monkeypatch the environment and name the fixture
        # without taking it; they run in the gate like any other module.
        and path.name != "test_testing_db_fixtures.py"
    }


def test_the_lane_runs_every_module_that_takes_the_fixture() -> None:
    command = _lane_command()
    missing = sorted(module for module in _modules_taking_the_fixture() if module not in command)
    assert not missing, f"never run on PostgreSQL in CI: {missing}"


def test_the_fixture_is_found_where_it_is_taken() -> None:
    """Held against the two modules known to take it, so an empty scan cannot pass."""
    assert {
        "tests/architecture/test_migrations_conformance.py",
        "tests/architecture/test_audit_activity.py",
    } <= _modules_taking_the_fixture()
