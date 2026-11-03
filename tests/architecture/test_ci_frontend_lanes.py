"""The frontend workflow's ``checks`` is green only when every lane is, and no lane passes empty.

``.github/workflows/frontend.yml`` runs its lanes as parallel jobs, and ``checks`` -- the name
the workflow has always reported, and the one a branch rule names -- stands for all of them. Two
things make that true and both are easy to lose in a tidy-up: ``checks`` waits for every other
job, and it runs whatever they did (``always()``), because GitHub reports a job skipped after a
failed dependency as a success. The accessibility lane is split with Playwright's ``--shard``,
which turns off the runner's refusal of a run that finds no tests, so each shard lists the whole
file first. Held here against the workflow as data; the image tag the browser jobs run in is
held by ``records and compares against the same browser build`` in the workbench's own suite.
"""

from __future__ import annotations

import pathlib
import re

import yaml

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_WORKBENCH = _REPO_ROOT / "apps" / "workbench"


def _jobs() -> dict:
    workflow = (_REPO_ROOT / ".github" / "workflows" / "frontend.yml").read_text(encoding="utf-8")
    return yaml.safe_load(workflow)["jobs"]


def _a11y_step() -> dict:
    steps = [step for step in _jobs()["workbench-a11y"]["steps"] if "--shard" in step.get("run", "")]
    assert len(steps) == 1, "expected one sharded accessibility step"
    return steps[0]


def test_checks_waits_for_every_other_job_and_runs_whatever_they_did() -> None:
    jobs = _jobs()
    checks = jobs["checks"]

    assert set(checks["needs"]) == set(jobs) - {"checks"}
    assert checks["if"] == "always()"
    (step,) = checks["steps"]
    assert step["env"]["RESULTS"] == "${{ join(needs.*.result, ' ') }}"
    assert '[ "$result" != "success" ]' in step["run"] and "exit 1" in step["run"]


def test_every_accessibility_shard_refuses_an_empty_lane_before_it_runs_its_part() -> None:
    step = _a11y_step()
    commands = [line.strip() for line in step["run"].splitlines() if "playwright test" in line]
    listed, sharded = commands[0], commands[-1]

    assert "--list" in listed and "--shard" not in listed
    # A bare command substitution: its status is the listing's, so the step's `bash -e` stops
    # on an empty lane. Piped (`... --list | tail -n 1`) the pipeline would answer for the
    # last command instead, and the refusal would be lost without pipefail.
    assert listed.startswith("listed=$(") and "|" not in listed
    assert "--shard" in sharded and "--list" not in sharded
    spec = re.search(r"visual/\S+\.spec\.ts", sharded)
    assert spec is not None and spec.group(0) in listed, "the list must be of the file the shards run"
    assert (_WORKBENCH / spec.group(0)).is_file()


def test_the_shard_is_the_matrix_position_not_a_value_written_in_it() -> None:
    env = _a11y_step()["env"]

    assert env == {"INDEX": "${{ strategy.job-index }}", "TOTAL": "${{ strategy.job-total }}"}


def test_every_workbench_lane_runs_in_ci() -> None:
    """The workbench's lanes once ran nowhere in CI; a lane added later must be wired in."""
    lanes = sorted(path.relative_to(_WORKBENCH).as_posix() for path in (_WORKBENCH / "visual").glob("*.spec.ts"))
    runs = "\n".join(step.get("run", "") for job in _jobs().values() for step in job["steps"])

    assert len(lanes) >= 4, "the scan stopped finding the workbench's lanes"
    assert [lane for lane in lanes if lane not in runs] == []
