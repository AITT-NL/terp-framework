"""The generated app's conformance job can start the stack it tests, and knows where it is.

The template ships a CI job that brings up the Docker workbench and runs the app's
Playwright suite against it. Two things kept it from ever passing on a freshly generated
app, and neither was visible from inside this repository:

* the workbench publishes its host ports through REQUIRED variables (ADR 0134), and the
  job never assigned them, so ``docker compose up`` refused to start at all;
* the suite's config fell back to a literal port the workbench no longer publishes, and
  nothing set the real one, so even a running stack was never the one it drove.

The framework's own conformance lane runs the example app, whose compose file keeps
in-range defaults, so it could not notice either. These are the static halves of the
fix; ``template-acceptance`` runs the generated job end to end, through
``tools/run_workflow_job.py``, from the rendered workflow itself.
"""

from __future__ import annotations

import pathlib
import re
import sys

import pytest
import yaml

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "packages" / "backend" / "cli" / "src"))
sys.path.insert(0, str(_REPO_ROOT / "tools"))

import run_workflow_job  # noqa: E402
from terp.cli.verify import CONFORMANCE_BASE_URL_ENV  # noqa: E402

_PROJECT = _REPO_ROOT / "template" / "project"
_TEMPLATE_CI = _PROJECT / ".github" / "workflows" / "ci.yml.jinja"
_SUITE_CONFIG = _PROJECT / "conformance" / "playwright.config.ts"
_FRAMEWORK_CI = _REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _conformance_steps() -> list[dict]:
    # The workflow carries no Jinja tags, so it parses as the YAML a generated app gets.
    workflow = yaml.safe_load(_TEMPLATE_CI.read_text(encoding="utf-8"))
    return workflow["jobs"]["conformance"]["steps"]


def _first_step_running(steps: list[dict], needle: str) -> int | None:
    for index, step in enumerate(steps):
        if needle in str(step.get("run", "")):
            return index
    return None


def test_the_conformance_job_assigns_ports_before_it_starts_the_workbench() -> None:
    """Compose refuses an unassigned checkout, and a fresh runner is one: ``.env`` is
    gitignored, so nothing the checkout carries can supply the pair. The assignment has
    to come first, and the check that reads it has to come after the stack is up."""
    steps = _conformance_steps()
    assign = _first_step_running(steps, "terp ports assign")
    start = _first_step_running(steps, "docker compose up")
    check = _first_step_running(steps, "--only conformance")
    assert start is not None and check is not None, "the job no longer starts or runs the suite"
    assert assign is not None, (
        "the conformance job starts the workbench without assigning its host ports; "
        "compose refuses with `required variable WEB_PORT is missing a value`. Add a "
        "`uv run terp ports assign` step before `docker compose up`."
    )
    assert assign < start < check, (
        f"steps out of order: ports assigned at {assign}, workbench started at {start}, "
        f"suite run at {check}"
    )


def test_the_template_suite_names_no_address_of_its_own() -> None:
    """The address is this checkout's assignment, which only the gate reads. A literal
    here is somebody else's port, so the config refuses rather than guessing."""
    config = _SUITE_CONFIG.read_text(encoding="utf-8")
    assert f"process.env.{CONFORMANCE_BASE_URL_ENV}" in config, (
        f"the suite no longer reads {CONFORMANCE_BASE_URL_ENV}, the variable "
        "`terp verify --only conformance` hands it"
    )
    fallback = re.search(rf"{CONFORMANCE_BASE_URL_ENV}\s*(\?\?|\|\|)", config)
    assert fallback is None, "the suite falls back to an address of its own"
    assert not re.search(r"https?://", config), "the suite names an address of its own"
    assert "throw new Error" in config, "an unset address must stop the suite, not default"


def _acceptance_scripts() -> list[str]:
    workflow = yaml.safe_load(_FRAMEWORK_CI.read_text(encoding="utf-8"))
    return [str(step.get("run", "")) for step in workflow["jobs"]["template-acceptance"]["steps"]]


def test_acceptance_runs_the_generated_job_and_the_runner_can_run_it() -> None:
    """``template-acceptance`` runs the rendered workflow's own conformance job, so the job
    it proves is the one every generated app ships. The runner refuses any form it does not
    implement, and any ``uses:`` step acceptance has not said it provides. Planned here with
    exactly the ``--provided`` list acceptance passes, so a template change the runner
    cannot follow fails in seconds, not at the end of an image build in CI."""
    invocations = [script for script in _acceptance_scripts() if "run_workflow_job.py" in script]
    assert len(invocations) == 1, (
        "template-acceptance must run the generated conformance job through "
        "tools/run_workflow_job.py, exactly once"
    )
    invocation = invocations[0]
    assert re.search(r"/\.github/workflows/ci\.yml conformance\b", invocation), invocation
    provided = frozenset(re.findall(r"--provided (\S+)", invocation))
    workflow = yaml.safe_load(_TEMPLATE_CI.read_text(encoding="utf-8"))
    try:
        run_workflow_job.plan(workflow, "conformance", provided=provided)
    except run_workflow_job.Refusal as refusal:
        pytest.fail(
            f"template-acceptance would refuse the template's conformance job: {refusal}. "
            "Keep the job within what tools/run_workflow_job.py implements, or extend the "
            "runner and its tests."
        )


def test_acceptance_does_not_restate_the_generated_job() -> None:
    """A copy of the job's steps in acceptance is the drift the runner removed: the copy
    goes on proving the steps it was taken from while the template's job moves on."""
    restated = [
        script
        for script in _acceptance_scripts()
        if "docker compose up" in script or "--only conformance" in script
    ]
    assert restated == [], (
        "template-acceptance starts the workbench or runs the suite itself; the generated "
        f"job does both, and acceptance runs that job: {restated}"
    )
