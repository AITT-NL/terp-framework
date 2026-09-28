"""``tools/run_workflow_job.py`` runs a workflow's job as Actions would, or refuses to.

``template-acceptance`` runs the generated app's conformance job through it, so that the
job it tests is the job every generated app ships, not a copy that can drift from it. That
is only true while the runner means what Actions means: steps in order, a failure stopping
the job and naming its step, ``always()`` and ``failure()`` steps still having their turn,
``working-directory`` and ``env`` honoured. And it stays true only while every form the
runner does not implement is refused rather than guessed at.

These run small fixture workflows, never the real one. That the template's job stays
within what the runner implements is ``test_template_conformance_job.py``'s concern.
"""

from __future__ import annotations

import pathlib
import sys
import textwrap

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "tools"))

import run_workflow_job as runner  # noqa: E402

#: The first step of every refusal fixture. A refusal happens before anything runs, so the
#: file this step would write must never appear.
_WOULD_HAVE_RUN = "- name: would have run\n  run: touch ran\n"


def _workflow(tmp_path: pathlib.Path, text: str) -> pathlib.Path:
    """A repository at *tmp_path*/app whose ci.yml is *text*; the workflow file's path."""
    path = tmp_path / "app" / ".github" / "workflows" / "ci.yml"
    path.parent.mkdir(parents=True)
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return path


def _job(steps: str, *, job: str = "", top: str = "", runs_on: str = "ubuntu-latest") -> str:
    """A one-job workflow: *top* at the workflow level, *job* at the job's, then *steps*."""
    return (
        f"name: ci\non: push\n{textwrap.dedent(top)}jobs:\n  conformance:\n"
        f"    runs-on: {runs_on}\n"
        + textwrap.indent(textwrap.dedent(job), "    ")
        + "    steps:\n"
        + textwrap.indent(textwrap.dedent(steps), "      ")
    )


def _run(path: pathlib.Path, *provided: str) -> int:
    argv = [str(path), "conformance"]
    for action in provided:
        argv += ["--provided", action]
    return runner.main(argv)


@pytest.fixture(autouse=True)
def _elsewhere(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # The process runs from somewhere other than the workspace, as the acceptance job's
    # does, so a step that ran in the caller's directory lands here and not in the app.
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)


def test_steps_run_in_file_order_in_the_workspace(tmp_path: pathlib.Path) -> None:
    # Named out of alphabetical order, so running them by name would change the log.
    path = _workflow(
        tmp_path,
        _job(
            """
            - name: zeta
              run: echo one >> log
            - name: alpha
              run: echo two >> log
            - run: echo three >> log
            """
        ),
    )
    assert _run(path) == 0
    workspace = path.parents[2]
    assert (workspace / "log").read_text() == "one\ntwo\nthree\n"
    assert not (tmp_path / "elsewhere" / "log").exists()


def test_working_directory_is_resolved_under_the_workspace(tmp_path: pathlib.Path) -> None:
    path = _workflow(
        tmp_path,
        _job(
            """
            - name: in a subdirectory
              working-directory: conformance
              run: touch here
            """
        ),
    )
    workspace = path.parents[2]
    (workspace / "conformance").mkdir()
    assert _run(path) == 0
    assert (workspace / "conformance" / "here").is_file()
    assert not (workspace / "here").exists()


def test_a_missing_working_directory_fails_its_step(
    tmp_path: pathlib.Path, capfd: pytest.CaptureFixture[str]
) -> None:
    path = _workflow(
        tmp_path,
        _job(
            """
            - name: nowhere
              working-directory: missing
              run: touch here
            """
        ),
    )
    assert _run(path) == 1
    err = capfd.readouterr().err
    assert "does not exist" in err
    assert "the job failed at step 'nowhere' (no working-directory)" in err


def test_a_failing_step_fails_the_job_by_name_and_the_cleanup_still_runs(
    tmp_path: pathlib.Path, capfd: pytest.CaptureFixture[str]
) -> None:
    path = _workflow(
        tmp_path,
        _job(
            """
            - name: passes
              run: echo passes >> log
            - name: breaks
              run: exit 3
            - name: after the break
              run: echo after >> log
            - name: cleans up
              if: always()
              run: echo always >> log
            - name: diagnoses
              if: failure()
              run: echo failure >> log
            """
        ),
    )
    assert _run(path) == 1
    assert (path.parents[2] / "log").read_text() == "passes\nalways\nfailure\n"
    captured = capfd.readouterr()
    assert "the job failed at step 'breaks' (exit 3)" in captured.err
    assert "--> not run: after the break (if: success())" in captured.out


def test_a_passing_job_runs_always_and_not_failure(tmp_path: pathlib.Path) -> None:
    path = _workflow(
        tmp_path,
        _job(
            """
            - name: passes
              run: echo passes >> log
            - name: diagnoses
              if: failure()
              run: echo failure >> log
            - name: cleans up
              if: always()
              run: echo always >> log
            """
        ),
    )
    assert _run(path) == 0
    assert (path.parents[2] / "log").read_text() == "passes\nalways\n"


def test_a_cleanup_that_fails_too_is_named_after_the_cause(
    tmp_path: pathlib.Path, capfd: pytest.CaptureFixture[str]
) -> None:
    path = _workflow(
        tmp_path,
        _job(
            """
            - name: breaks
              run: exit 3
            - name: cleans up badly
              if: always()
              run: exit 4
            """
        ),
    )
    assert _run(path) == 1
    err = capfd.readouterr().err
    assert "the job failed at step 'breaks' (exit 3)" in err
    assert "and step 'cleans up badly' (exit 4) failed after it" in err


def test_bash_runs_the_way_actions_invokes_it(tmp_path: pathlib.Path) -> None:
    """``bash -e`` with no shell named, and ``-o pipefail`` only for ``shell: bash``: the
    two command lines Actions documents, which differ exactly on a failing pipe."""
    errexit = _workflow(tmp_path / "errexit", _job("- run: |\n    false\n    touch after\n"))
    assert _run(errexit) == 1
    assert not (errexit.parents[2] / "after").exists()

    default = _workflow(tmp_path / "default", _job("- run: |\n    false | true\n    touch after\n"))
    assert _run(default) == 0
    assert (default.parents[2] / "after").is_file()

    named = _workflow(
        tmp_path / "named",
        _job("- shell: bash\n  run: |\n    false | true\n    touch after\n"),
    )
    assert _run(named) == 1
    assert not (named.parents[2] / "after").exists()


def test_env_is_the_callers_then_the_jobs_then_the_steps(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A different value at every layer, so dropping any one of them changes the output.
    monkeypatch.setenv("FROM_CALLER", "caller")
    monkeypatch.setenv("JOB_WINS", "caller")
    path = _workflow(
        tmp_path,
        _job(
            """
            - env:
                STEP_WINS: step
              run: printf '%s %s %s' "$FROM_CALLER" "$JOB_WINS" "$STEP_WINS" > env.txt
            """,
            job="""
            env:
              JOB_WINS: job
              STEP_WINS: job
            """,
        ),
    )
    assert _run(path) == 0
    assert (path.parents[2] / "env.txt").read_text() == "caller job step"


def test_github_workspace_is_the_workflows_repository(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path / "the-callers-checkout"))
    path = _workflow(tmp_path, _job("""- run: printf '%s' "$GITHUB_WORKSPACE" > ws.txt\n"""))
    assert _run(path) == 0
    workspace = path.parents[2]
    assert pathlib.Path((workspace / "ws.txt").read_text()) == workspace.resolve()


def test_a_file_command_cannot_reach_the_callers_step(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Inherited, ``$GITHUB_ENV`` is the caller's step file: the write would land there,
    succeed, and set nothing for this job's next step. Removed, it fails where it is."""
    callers = tmp_path / "callers-github-env"
    callers.write_text("")
    monkeypatch.setenv("GITHUB_ENV", str(callers))
    path = _workflow(tmp_path, _job("""- run: echo LEAKED=1 >> "$GITHUB_ENV"\n"""))
    assert _run(path) == 1
    assert callers.read_text() == ""


def test_a_provided_action_is_skipped_by_name(
    tmp_path: pathlib.Path, capfd: pytest.CaptureFixture[str]
) -> None:
    path = _workflow(
        tmp_path,
        _job(
            """
            - uses: actions/checkout@0123abcd # v9
              with:
                persist-credentials: false
            - name: Upload on failure
              if: failure()
              uses: actions/upload-artifact@4567ef01
            - run: touch ran
            """
        ),
    )
    assert _run(path, "actions/checkout", "actions/upload-artifact") == 0
    out = capfd.readouterr().out
    assert (
        "--> skipped: Run actions/checkout@0123abcd "
        "(actions/checkout@0123abcd; the caller provides it)"
    ) in out
    assert "--> skipped: Upload on failure (actions/upload-artifact@4567ef01;" in out
    assert (path.parents[2] / "ran").is_file()


@pytest.mark.parametrize(
    ("text", "refusal"),
    [
        pytest.param(
            _job(_WOULD_HAVE_RUN + "- uses: docker/setup-buildx-action@89ab\n"),
            "uses docker/setup-buildx-action, and the caller has not said it provides it",
            id="an action nobody provides",
        ),
        pytest.param(
            _job(_WOULD_HAVE_RUN + "- if: success()\n  run: 'true'\n"),
            "has `if: success()`, which this runner does not evaluate",
            id="an if it does not evaluate",
        ),
        pytest.param(
            _job(_WOULD_HAVE_RUN + "- if: cancelled()\n  run: 'true'\n"),
            "has `if: cancelled()`",
            id="another status function",
        ),
        pytest.param(
            _job(_WOULD_HAVE_RUN + "- if: always() && failure()\n  uses: actions/checkout@1\n"),
            "has `if: always() && failure()`",
            id="an unknown if on a provided action",
        ),
        pytest.param(
            _job(_WOULD_HAVE_RUN + "- if: ${{ always() }}\n  run: 'true'\n"),
            "if holds a ${{ }} expression",
            id="an if written as an expression",
        ),
        pytest.param(
            _job(_WOULD_HAVE_RUN + "- run: echo ${{ github.sha }}\n"),
            "run holds a ${{ }} expression",
            id="an expression in a script",
        ),
        pytest.param(
            _job(_WOULD_HAVE_RUN + "- env:\n    SHA: ${{ github.sha }}\n  run: 'true'\n"),
            "env SHA holds a ${{ }} expression",
            id="an expression in a step's env",
        ),
        pytest.param(
            _job(_WOULD_HAVE_RUN, job="env:\n  SHA: ${{ github.sha }}\n"),
            "job 'conformance' env SHA holds a ${{ }} expression",
            id="an expression in the job's env",
        ),
        pytest.param(
            _job(_WOULD_HAVE_RUN + "- working-directory: ${{ github.workspace }}\n  run: 'true'\n"),
            "working-directory holds a ${{ }} expression",
            id="an expression in a working-directory",
        ),
        pytest.param(
            _job(_WOULD_HAVE_RUN + "- name: build ${{ matrix.variant }}\n  run: 'true'\n"),
            "name holds a ${{ }} expression",
            id="an expression in a name",
        ),
        pytest.param(
            _job(_WOULD_HAVE_RUN + "- shell: sh\n  run: 'true'\n"),
            "runs with `shell: sh`; this runner runs bash only",
            id="another shell",
        ),
        pytest.param(
            _job(_WOULD_HAVE_RUN + "- shell: pwsh\n  run: 'true'\n"),
            "`shell: pwsh`",
            id="a shell that is not a posix one",
        ),
        pytest.param(
            _job(_WOULD_HAVE_RUN + "- env:\n    PORT: 8080\n  run: 'true'\n"),
            "env PORT is 8080; this runner reads strings only",
            id="an env value that is not a string",
        ),
        pytest.param(
            _job(_WOULD_HAVE_RUN + "- continue-on-error: true\n  run: 'true'\n"),
            "step 2 sets continue-on-error, which this runner has no meaning for",
            id="a step key it has no meaning for",
        ),
        pytest.param(
            _job(_WOULD_HAVE_RUN + "- run: 'true'\n  with:\n    x: y\n"),
            "step 2 sets with, which this runner has no meaning for",
            id="an action input on a script",
        ),
        pytest.param(
            _job(_WOULD_HAVE_RUN + "- run: 'true'\n  uses: actions/checkout@1\n"),
            "step 2 must have exactly one of run: and uses:",
            id="a script and an action",
        ),
        pytest.param(
            _job(_WOULD_HAVE_RUN + "- name: neither\n"),
            "step 2 must have exactly one of run: and uses:",
            id="neither a script nor an action",
        ),
        pytest.param(
            _job(_WOULD_HAVE_RUN + "- echo hi\n"),
            "step 2 is not a mapping",
            id="a step that is not a mapping",
        ),
        pytest.param(
            _job(_WOULD_HAVE_RUN, job="services:\n  db:\n    image: postgres\n"),
            "job 'conformance' sets services, which this runner has no meaning for",
            id="a job key it has no meaning for",
        ),
        pytest.param(
            _job(_WOULD_HAVE_RUN, runs_on="windows-latest"),
            "runs on 'windows-latest'; this runner knows an ubuntu runner's default shell only",
            id="a runner whose default shell is not bash",
        ),
        pytest.param(
            _job(_WOULD_HAVE_RUN, top="env:\n  X: y\n"),
            "the workflow sets env, which this runner has no meaning for",
            id="a workflow env",
        ),
        pytest.param(
            _job(_WOULD_HAVE_RUN, top="defaults:\n  run:\n    shell: sh\n"),
            "the workflow sets defaults, which this runner has no meaning for",
            id="workflow defaults",
        ),
        pytest.param(
            "name: ci\non: push\njobs:\n  gate:\n    runs-on: ubuntu-latest\n    steps: []\n",
            "the workflow has no job 'conformance'; its jobs are gate",
            id="no such job",
        ),
        pytest.param(
            "name: ci\non: push\njobs:\n  conformance:\n    runs-on: ubuntu-latest\n    steps: []\n",
            "job 'conformance' has no steps",
            id="a job with no steps",
        ),
        pytest.param("- a list\n", "the workflow is not a mapping", id="not a workflow"),
    ],
)
def test_what_it_does_not_implement_is_refused_before_anything_runs(
    tmp_path: pathlib.Path, capfd: pytest.CaptureFixture[str], text: str, refusal: str
) -> None:
    path = _workflow(tmp_path, text)
    assert _run(path, "actions/checkout") == 2
    err = capfd.readouterr().err
    assert f"refusing to run job 'conformance' of {path}: " in err
    assert refusal in err
    assert not (path.parents[2] / "ran").exists(), "a refusal must come before any step runs"


def test_a_workflow_outside_github_workflows_has_no_workspace(
    tmp_path: pathlib.Path, capfd: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "ci.yml"
    path.write_text(_job("- run: 'true'\n"), encoding="utf-8")
    assert _run(path) == 2
    assert "is not in a repository's .github/workflows/" in capfd.readouterr().err


def test_no_bash_is_a_refusal(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(runner.shutil, "which", lambda _name: None)
    path = _workflow(tmp_path, _job("- run: touch ran\n"))
    assert _run(path) == 2
    assert "there is no bash on PATH" in capfd.readouterr().err
    assert not (path.parents[2] / "ran").exists()
