"""The release lane runs where it says it runs, and nowhere it would pass by skipping.

The lane (``tests/release_lane``, ADR 0187 decision 8's sixth pull request) proves ``terp
release`` and ``terp promote`` on a Docker engine. It skips without one, which is green, so the
only job that runs it sets ``TERP_REQUIRE_RELEASE_LANE`` and turns the skip into a failure, as
the PostgreSQL lane does with ``TERP_REQUIRE_POSTGRES_LANE``. The gate deselects it by marker:
fifteen minutes of cold builds is no part of a unit run. Held here, against the workflow and
the pytest configuration as data, and against the lane's own skip.
"""

from __future__ import annotations

import pathlib
import re
import tomllib

import pytest
import yaml

from tests.release_lane import lane

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_LANE_STEP = "Run the release lane on the runner's engine"


def _lane_step() -> dict:
    workflow = yaml.safe_load((_REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    for job in workflow["jobs"].values():
        for step in job.get("steps", ()):
            if step.get("name") == _LANE_STEP:
                return step
    raise AssertionError(f"no CI step named {_LANE_STEP!r}")


def _modules_marked() -> set[str]:
    marked = re.compile(r"pytest\.mark\.release_lane\b")
    return {
        path.relative_to(_REPO_ROOT).as_posix()
        for path in (_REPO_ROOT / "tests").rglob("test_*.py")
        if path.name != pathlib.Path(__file__).name and marked.search(path.read_text(encoding="utf-8"))
    }


def test_the_lane_job_runs_every_marked_module_and_a_skip_fails_it() -> None:
    step = _lane_step()
    assert step["env"][lane.REQUIRE_ENV] == "1", "a skip in the lane must fail"
    command = step["run"].split()
    assert command[command.index("-m") + 1] == "release_lane"
    modules = _modules_marked()
    assert modules >= {"tests/release_lane/test_release_lane.py"}, "an empty scan proves nothing"
    assert all(any(module.startswith(part.rstrip("/") + "/") or module == part for part in command) for module in modules), (
        modules, command)


def test_the_gate_deselects_the_lane_and_knows_its_marker() -> None:
    config = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["pytest"]["ini_options"]
    assert "-m 'not release_lane'" in config["addopts"]
    assert any(marker.startswith("release_lane:") for marker in config["markers"])


def test_the_lane_skips_without_an_engine_and_fails_where_it_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    """Either outcome is caught and its kind asserted: a skip escaping a ``raises`` that waits
    for a failure would skip this test too, and a skip is green."""
    monkeypatch.delenv(lane.REQUIRE_ENV, raising=False)
    with pytest.raises(BaseException) as skipped:  # noqa: PT011 - the kind is asserted below
        lane.unavailable("no engine here")
    assert skipped.type is pytest.skip.Exception and "no engine here" in str(skipped.value)
    monkeypatch.setenv(lane.REQUIRE_ENV, "1")
    with pytest.raises(BaseException) as failed:  # noqa: PT011 - the kind is asserted below
        lane.unavailable("no engine here")
    assert failed.type is pytest.fail.Exception, failed.type
    assert f"no engine here. {lane.REQUIRE_ENV} is set" in str(failed.value)


def test_the_lane_names_what_it_makes_under_one_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(lane.PREFIX_ENV, raising=False)
    assert lane.prefix() == lane.DEFAULT_PREFIX
    monkeypatch.setenv(lane.PREFIX_ENV, "ci2-")
    assert lane.prefix() == "ci2-"
    for wrong in ("CI2-", "ci2", "-ci2-", "c i2-", "terp-lane-name-that-is-far-too-long-"):
        monkeypatch.setenv(lane.PREFIX_ENV, wrong)
        with pytest.raises(ValueError, match=lane.PREFIX_ENV):
            lane.prefix()
