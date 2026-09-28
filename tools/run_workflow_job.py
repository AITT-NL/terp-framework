"""Run one job of a checked-in GitHub Actions workflow as Actions would, or refuse to.

``template-acceptance`` used to restate the generated app's conformance job step by step:
assign the ports, start the workbench, seed, verify. The copy and the job were separate
text, so they could drift: someone edits the job every generated app ships, and acceptance
goes on proving the steps it copied. This runs the rendered workflow's own job instead, so
the job that is tested is the job that ships.

What it does is what an ``ubuntu-*`` runner does with the same job:

* each ``run:`` step is written to a script file and run with bash, the way Actions invokes
  it: ``bash -e {0}`` when the step names no shell, ``bash --noprofile --norc -eo pipefail
  {0}`` for ``shell: bash``;
* in the workspace, which is the repository the workflow file is checked into, or in the
  step's ``working-directory`` under it;
* with the caller's environment, overlaid by the job's ``env`` and then by the step's;
* a step with no ``if:`` runs while no step before it has failed, ``if: always()`` runs
  regardless, and ``if: failure()`` runs only once one has;
* a ``uses:`` step is skipped, with a line naming it, when the caller has said it provides
  that action's equivalent itself (``--provided``). It cannot run an action, and does not
  pretend to.

The job fails naming the first step that failed, after its ``always()`` and ``failure()``
steps have had their turn.

**It refuses what it does not understand, before it runs anything:** any other ``if:``,
any other ``shell:``, a ``${{ }}`` expression in a field it reads, a ``uses:`` step the
caller has not said it provides, a runner other than ``ubuntu-*`` (whose default shell is
not bash), and any key it has no meaning for. A runner that guessed would be a second copy
of the job with opinions of its own, which is the drift this exists to remove, moved one
file over. The forms it supports are the ones the generated conformance job uses; the next
one is a change here and a test in ``tests/architecture/test_run_workflow_job.py``.

Two parts of the environment belong to the job, not to the caller. ``GITHUB_WORKSPACE`` is
the workspace above. And Actions' file commands (``GITHUB_ENV``, ``GITHUB_OUTPUT``,
``GITHUB_PATH``, ``GITHUB_STATE``, ``GITHUB_STEP_SUMMARY``) are removed: inherited, they
name the *caller's* step files, so a line a step writes for the next step of this job would
land in the caller's step and change nothing here. Removed, the write fails, and the step
with it.

Start it with an interpreter that announces no environment of its own. ``uv run`` puts its
project's ``.venv`` first on ``PATH`` and sets ``VIRTUAL_ENV``, and every step inherits
both.
"""

from __future__ import annotations

import argparse
import dataclasses
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterable, Mapping, Sequence

import yaml


class Refusal(Exception):
    """The workflow uses a form this runner does not implement."""


#: Workflow keys that change nothing about how one job's steps run.
_WORKFLOW_KEYS = frozenset({"name", "on", "permissions", "jobs"})
#: Job keys this runner reads. ``runs-on`` decides the default shell, so it is checked.
_JOB_KEYS = frozenset({"runs-on", "env", "steps"})
#: Step keys this runner reads, by the kind of step. ``with`` is an action's input, and a
#: provided action is not run, so it is never read.
_STEP_KEYS = {
    "run": frozenset({"name", "run", "if", "working-directory", "env", "shell"}),
    "uses": frozenset({"name", "uses", "with", "if"}),
}
#: The ``if:`` a step may write. Without one, a step runs as ``success()``.
_CONDITIONS = frozenset({"always()", "failure()"})
#: Bash's flags as Actions invokes it, by the step's ``shell:`` (None: the step names none).
_SHELLS: dict[str | None, tuple[str, ...]] = {
    None: ("-e",),
    "bash": ("--noprofile", "--norc", "-eo", "pipefail"),
}
#: Actions' file commands, which name the step files of whichever step is running.
_FILE_COMMANDS = frozenset(
    {"GITHUB_ENV", "GITHUB_OUTPUT", "GITHUB_PATH", "GITHUB_STATE", "GITHUB_STEP_SUMMARY"}
)


@dataclasses.dataclass(frozen=True)
class Run:
    """A ``run:`` step, resolved: what to run, where, with what, and when."""

    name: str
    script: str
    condition: str
    working_directory: str
    env: Mapping[str, str]
    flags: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class Provided:
    """A ``uses:`` step whose equivalent the caller has already done."""

    name: str
    uses: str


def _mapping(value: object, where: str) -> dict:
    if not isinstance(value, dict):
        raise Refusal(f"{where} is not a mapping")
    return value


def _literal(value: object, where: str) -> str:
    """*value* as the plain string Actions would hand over, or a refusal."""
    if not isinstance(value, str):
        raise Refusal(f"{where} is {value!r}; this runner reads strings only, so quote it")
    if "${{" in value:
        raise Refusal(f"{where} holds a ${{{{ }}}} expression, which this runner cannot evaluate")
    return value


def _unknown(keys: Iterable[object], known: frozenset[str], where: str) -> None:
    extra = sorted(str(key) for key in keys if key not in known)
    if extra:
        raise Refusal(f"{where} sets {', '.join(extra)}, which this runner has no meaning for")


def _env(value: object, where: str) -> dict[str, str]:
    return {
        _literal(key, f"{where} env key {key!r}"): _literal(item, f"{where} env {key}")
        for key, item in _mapping(value, f"{where} env").items()
    }


def _step(
    raw: object, index: int, job_env: Mapping[str, str], provided: frozenset[str]
) -> Run | Provided:
    step = _mapping(raw, f"step {index}")
    kinds = [kind for kind in _STEP_KEYS if kind in step]
    if len(kinds) != 1:
        raise Refusal(f"step {index} must have exactly one of run: and uses:")
    kind = kinds[0]
    _unknown(step, _STEP_KEYS[kind], f"step {index}")
    body = _literal(step[kind], f"step {index} {kind}")
    # Actions' own label for a step without a name.
    first_line = body.partition("\n")[0]
    name = _literal(step.get("name", f"Run {first_line}"), f"step {index} name")
    where = f"step {index} ({name!r})"
    condition = _literal(step.get("if", "success()"), f"{where} if")
    if "if" in step and condition not in _CONDITIONS:
        raise Refusal(
            f"{where} has `if: {condition}`, which this runner does not evaluate; "
            f"it knows {' and '.join(sorted(_CONDITIONS))}"
        )
    if kind == "uses":
        action = body.partition("@")[0]
        if action not in provided:
            raise Refusal(
                f"{where} uses {action}, and the caller has not said it provides it; do its "
                f"equivalent before the runner and pass --provided {action}"
            )
        return Provided(name=name, uses=body)
    shell = _literal(step["shell"], f"{where} shell") if "shell" in step else None
    if shell not in _SHELLS:
        raise Refusal(f"{where} runs with `shell: {shell}`; this runner runs bash only")
    return Run(
        name=name,
        script=body,
        condition=condition,
        working_directory=_literal(
            step.get("working-directory", "."), f"{where} working-directory"
        ),
        env={**job_env, **_env(step.get("env", {}), where)},
        flags=_SHELLS[shell],
    )


def plan(workflow: object, job_id: str, *, provided: frozenset[str]) -> list[Run | Provided]:
    """The steps of *job_id*, resolved, or a :class:`Refusal` naming what is not understood.

    Every step is resolved before any runs, so a refusal never leaves a job half-run.
    """
    workflow = _mapping(workflow, "the workflow")
    # PyYAML reads a bare `on` key as YAML 1.1's boolean true; Actions reads it as `on`.
    _unknown(("on" if key is True else key for key in workflow), _WORKFLOW_KEYS, "the workflow")
    jobs = _mapping(workflow.get("jobs"), "the workflow's jobs")
    if job_id not in jobs:
        known = ", ".join(map(str, jobs))
        raise Refusal(f"the workflow has no job {job_id!r}; its jobs are {known}")
    job = _mapping(jobs[job_id], f"job {job_id!r}")
    _unknown(job, _JOB_KEYS, f"job {job_id!r}")
    runs_on = job.get("runs-on")
    if not (isinstance(runs_on, str) and runs_on.startswith("ubuntu-")):
        raise Refusal(
            f"job {job_id!r} runs on {runs_on!r}; this runner knows an ubuntu runner's "
            "default shell only"
        )
    job_env = _env(job.get("env", {}), f"job {job_id!r}")
    steps = job.get("steps")
    if not isinstance(steps, list) or not steps:
        raise Refusal(f"job {job_id!r} has no steps")
    return [_step(raw, index, job_env, provided) for index, raw in enumerate(steps, 1)]


def workspace_of(workflow: pathlib.Path) -> pathlib.Path:
    """The repository *workflow* is checked into, which is Actions' workspace for its jobs."""
    path = workflow.resolve()
    if (path.parent.name, path.parent.parent.name) != ("workflows", ".github"):
        raise Refusal(f"{workflow} is not in a repository's .github/workflows/")
    return path.parents[2]


def _due(condition: str, *, failing: bool) -> bool:
    """Whether a step on *condition* runs, given whether a step before it has failed."""
    return {"success()": not failing, "always()": True, "failure()": failing}[condition]


def _say(line: str) -> None:
    # Flushed, so the line lands before the output of the step it introduces.
    print(line, flush=True)


def execute(
    steps: Sequence[Run | Provided],
    *,
    workspace: pathlib.Path,
    environ: Mapping[str, str],
    bash: str,
) -> int:
    """Run *steps* in *workspace*; 0 when every step that ran passed, 1 otherwise."""
    base = {key: value for key, value in environ.items() if key not in _FILE_COMMANDS}
    base["GITHUB_WORKSPACE"] = str(workspace)
    failed: list[str] = []
    with tempfile.TemporaryDirectory(prefix="run-workflow-job-") as scratch:
        for index, step in enumerate(steps, 1):
            if isinstance(step, Provided):
                _say(f"--> skipped: {step.name} ({step.uses}; the caller provides it)")
                continue
            if not _due(step.condition, failing=bool(failed)):
                _say(f"--> not run: {step.name} (if: {step.condition})")
                continue
            _say(f"==> {step.name}")
            cwd = workspace / step.working_directory
            if not cwd.is_dir():
                print(f"working-directory {cwd} does not exist", file=sys.stderr)
                failed.append(f"{step.name!r} (no working-directory)")
                continue
            script = pathlib.Path(scratch) / f"step-{index}.sh"
            # LF on every platform: bash reads a CR as part of the command.
            script.write_text(step.script, encoding="utf-8", newline="\n")
            code = subprocess.run(  # noqa: S603 - bash from PATH, the workflow's own script
                [bash, *step.flags, str(script)],
                cwd=cwd,
                env={**base, **step.env},
                check=False,
            ).returncode
            if code != 0:
                failed.append(f"{step.name!r} (exit {code})")
    if not failed:
        return 0
    print(f"the job failed at step {failed[0]}", file=sys.stderr)
    for later in failed[1:]:
        print(f"and step {later} failed after it", file=sys.stderr)
    return 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("workflow", type=pathlib.Path, help="a file in .github/workflows/")
    parser.add_argument("job", help="the id of the job to run")
    parser.add_argument(
        "--provided",
        action="append",
        default=[],
        metavar="ACTION",
        help="an action (owner/name, without @ref) whose equivalent the caller has done",
    )
    args = parser.parse_args(argv)
    bash = shutil.which("bash")
    try:
        workspace = workspace_of(args.workflow)
        workflow = yaml.safe_load(args.workflow.read_text(encoding="utf-8"))
        steps = plan(workflow, args.job, provided=frozenset(args.provided))
        if bash is None:
            raise Refusal("there is no bash on PATH to run the steps with")
    except Refusal as refusal:
        print(f"refusing to run job {args.job!r} of {args.workflow}: {refusal}", file=sys.stderr)
        return 2
    return execute(steps, workspace=workspace, environ=os.environ, bash=bash)


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(main())
