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
fix; ``template-acceptance`` runs the generated suite end to end.
"""

from __future__ import annotations

import pathlib
import re
import sys

import yaml

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "packages" / "backend" / "cli" / "src"))

from terp.cli.verify import CONFORMANCE_BASE_URL_ENV  # noqa: E402

_PROJECT = _REPO_ROOT / "template" / "project"
_TEMPLATE_CI = _PROJECT / ".github" / "workflows" / "ci.yml.jinja"
_SUITE_CONFIG = _PROJECT / "conformance" / "playwright.config.ts"


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
