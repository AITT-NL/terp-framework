"""The release workflow's per-package publish contract (ADR 0063).

Terp releases in lockstep from a tag: one ``v<version>`` publishes every backend
distribution, every frontend package, and the images together. But a multi-package
release pipeline also needs a manual, single-package publish to PyPI for two
recurring reasons a tag cannot serve:

* **First-time project creation** — PyPI trusted publishing cannot pre-register
  every not-yet-existing project at once (a pending publisher's identity of
  ``(owner, repo, workflow, environment)`` is unique), so brand-new projects are
  necessarily created one at a time.
* **Backfill** — re-publishing one distribution whose upload failed mid-release.

That path must publish through the SAME attested trusted-publishing step (same
workflow file + ``release`` environment) and must NEVER cut a platform release
(no npm publish, no image push, no GitHub Release). These assertions hold the
checked-in workflow to that contract.
"""

from __future__ import annotations

import pathlib

import yaml

_WORKFLOW = (
    pathlib.Path(__file__).resolve().parents[2] / ".github" / "workflows" / "release.yml"
)

_PUSH_ONLY = "github.event_name == 'push'"
_DISPATCH_ONLY = "github.event_name == 'workflow_dispatch'"


def _workflow() -> dict:
    assert _WORKFLOW.is_file(), f"{_WORKFLOW} is missing"
    return yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))


def _triggers(workflow: dict) -> dict:
    # PyYAML parses the bare ``on:`` key as the boolean ``True`` (YAML 1.1).
    for key in ("on", True):
        if key in workflow:
            return workflow[key]
    raise AssertionError("release workflow declares no triggers")


def _step(job: dict, name: str) -> dict:
    for step in job["steps"]:
        if step.get("name") == name:
            return step
    raise AssertionError(f"step {name!r} not found")


def test_workflow_triggers_on_tag_and_manual_dispatch() -> None:
    triggers = _triggers(_workflow())
    assert triggers["push"]["tags"] == ["v*"], "lockstep tag trigger must stay v*"

    dispatch = triggers["workflow_dispatch"]
    package = dispatch["inputs"]["package"]
    assert package["required"] is True, "the package input must be required"
    assert package["type"] == "string", "the package input is a distribution path"


def test_tag_version_check_is_push_only() -> None:
    """A manual dispatch has no tag, so the tag-vs-version guard must not run."""
    verify = _workflow()["jobs"]["verify"]
    assert _step(verify, "Tag matches the lockstep version")["if"] == _PUSH_ONLY


def test_pypi_job_runs_on_both_events_via_trusted_publishing() -> None:
    """publish-pypi is the shared attested path — it must run for a tag AND a
    dispatch (no push-only job guard) and keep OIDC trusted publishing."""
    job = _workflow()["jobs"]["publish-pypi"]
    assert "if" not in job, "publish-pypi must run on both tag and dispatch"
    assert job["environment"] == "release", "trusted publisher is bound to env release"
    assert job["permissions"]["id-token"] == "write", "OIDC token for trusted publishing"

    publish = _step(job, "Publish to PyPI (trusted publishing)")
    assert publish["uses"].startswith("pypa/gh-action-pypi-publish")
    assert publish["with"]["packages-dir"] == "dist"


def test_lockstep_build_is_push_only_and_single_build_is_dispatch_only() -> None:
    """The two build steps feed the same dist/, gated by mutually exclusive
    events: all packages on a tag, exactly the named one on a dispatch."""
    job = _workflow()["jobs"]["publish-pypi"]

    all_packages = _step(job, "Build wheels + sdists for every backend distribution")
    assert all_packages["if"] == _PUSH_ONLY

    single = _step(job, "Build a single backend distribution (manual bootstrap/backfill)")
    assert single["if"] == _DISPATCH_ONLY
    run = single["run"]
    assert "inputs.package" in run, "the dispatch build must publish the named package"
    assert "packages/backend/" in run, "it must fail closed on a non-backend path"
    assert "uv build --out-dir dist" in run, "both build paths feed the same dist/"


def test_dispatch_never_cuts_a_platform_release() -> None:
    """A manual single-package publish must NOT publish npm, push images, or
    create a GitHub Release — those legs are tag-only."""
    jobs = _workflow()["jobs"]
    for name in ("publish-npm", "publish-images", "github-release"):
        assert jobs[name].get("if") == _PUSH_ONLY, f"{name} must stay tag-only"
