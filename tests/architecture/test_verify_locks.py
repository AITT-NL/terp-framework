"""``terp verify --only locks``: a managed app's images can be built from what it commits.

The template's production images install exactly ``uv.lock`` and
``frontend/package-lock.json`` (``uv sync --locked --no-dev``, ``npm ci``) and refuse a lock
that is missing or stale. So for an app a deploy tool builds, the ones whose
``deployment.json`` declares units (ADR 0184), a lock left behind by a dependency change is
an image that cannot be built, and this check says so on the gate with the file and the
command that fixes it. Any other app hears the same as a note.

Most cases replace the package managers with a recorded answer, so what is held is the
check's own logic; two run the real ``uv`` and ``npm`` offline against a lock they wrote, so
the commands it asks are proven to give the answer it reads.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

import pytest

from terp.cli import main
from terp.cli import verify as verify_module
from terp.cli.locks import LOCKS, run_locks_check
from tests.architecture.deployment_fixtures import project, seed

_PYPROJECT = (
    '[project]\nname = "locked-app"\nversion = "0.1.0"\nrequires-python = ">=3.13"\n'
    "dependencies = []\n"
)
_PACKAGE = json.dumps({"name": "locked-app-frontend", "version": "0.1.0", "private": True})


def _app(tmp_path: pathlib.Path, declaration: dict | str | None, **files: str) -> pathlib.Path:
    layout = {"pyproject.toml": _PYPROJECT, "uv.lock": "version = 1\n"}
    layout.update(files)
    return project(
        tmp_path, declaration, files={name: text for name, text in layout.items() if text}
    )


def _managed(tmp_path: pathlib.Path, **files: str) -> pathlib.Path:
    return _app(tmp_path, seed(), **files)


def _answers(monkeypatch: pytest.MonkeyPatch, **codes: int) -> list[list[str]]:
    """Answer each tool (``uv``, ``npm``) with an exit code; record what was asked."""
    asked: list[list[str]] = []

    def run(argv: list[str], root: pathlib.Path, *, env: dict | None = None):
        asked.append(argv)
        code = codes.get(argv[0], 0)
        said = "The lockfile at `uv.lock` needs to be updated" if code else ""
        return subprocess.CompletedProcess(argv, code, stdout=said, stderr="")

    monkeypatch.setattr(verify_module, "_run_argv", run)
    return asked


def test_a_managed_app_whose_locks_answer_their_manifests_passes(tmp_path, monkeypatch) -> None:
    root = _managed(
        tmp_path,
        **{"frontend/package.json": _PACKAGE, "frontend/package-lock.json": "{}"},
    )
    asked = _answers(monkeypatch)
    code, output = run_locks_check(root)
    assert code == 0
    assert output == (
        "uv.lock answers pyproject.toml, frontend/package-lock.json answers "
        "frontend/package.json: the locks the production images install"
    )
    # Each package manager is asked in its own words, offline, changing nothing.
    assert asked == [list(lock.check) for lock in LOCKS]
    assert all("--offline" in argv for argv in asked)
    assert "--dry-run" in asked[1] and "ci" in asked[1]


def test_a_managed_app_without_a_frontend_holds_only_its_backend_lock(
    tmp_path, monkeypatch
) -> None:
    asked = _answers(monkeypatch)
    code, output = run_locks_check(_managed(tmp_path))
    assert code == 0
    assert output == "uv.lock answers pyproject.toml: the locks the production images install"
    assert [argv[0] for argv in asked] == ["uv"]


def test_a_missing_backend_lock_refuses_a_managed_app_and_names_the_fix(
    tmp_path, monkeypatch
) -> None:
    asked = _answers(monkeypatch)
    code, output = run_locks_check(_managed(tmp_path, **{"uv.lock": ""}))
    assert code == 1
    assert "- uv.lock is missing. The production image installs exactly it" in output
    assert "(`uv sync --locked --no-dev`), so the image cannot be built." in output
    assert "Fix: uv lock, then commit uv.lock." in output
    assert asked == [], "a missing file is known without asking the tool"


def test_a_missing_frontend_lock_refuses_a_managed_app_and_names_the_fix(
    tmp_path, monkeypatch
) -> None:
    _answers(monkeypatch)
    root = _managed(tmp_path, **{"frontend/package.json": _PACKAGE})
    code, output = run_locks_check(root)
    assert code == 1
    assert "- frontend/package-lock.json is missing." in output
    assert "Fix: npm --prefix frontend install, then commit frontend/package-lock.json." in output
    assert "uv.lock" not in output.split("\n\n")[-1], "the backend lock was fine"


def test_a_stale_lock_refuses_a_managed_app_with_the_tools_own_answer(
    tmp_path, monkeypatch
) -> None:
    _answers(monkeypatch, uv=1)
    code, output = run_locks_check(_managed(tmp_path))
    assert code == 1
    assert output.startswith("A lock the production images install is missing or stale.")
    assert (
        "- uv.lock is stale against pyproject.toml: `uv lock --check --offline` refuses it, "
        "and the image's `uv sync --locked --no-dev` would stop at the same point."
    ) in output
    assert "Fix: uv lock, then commit uv.lock." in output
    assert "    The lockfile at `uv.lock` needs to be updated" in output


def test_a_stale_frontend_lock_names_npm_and_its_fix(tmp_path, monkeypatch) -> None:
    _answers(monkeypatch, npm=1)
    root = _managed(
        tmp_path,
        **{"frontend/package.json": _PACKAGE, "frontend/package-lock.json": "{}"},
    )
    code, output = run_locks_check(root)
    assert code == 1
    assert "- frontend/package-lock.json is stale against frontend/package.json" in output
    assert "the image's `npm ci` would stop at the same point" in output
    assert "Fix: npm --prefix frontend install, then commit frontend/package-lock.json." in output


def test_a_tool_that_is_not_installed_is_a_refusal_not_a_pass(tmp_path, monkeypatch) -> None:
    # Fail closed: a lock nobody could check is not a lock that answers its manifest.
    _answers(monkeypatch, uv=verify_module._NOT_FOUND)
    code, output = run_locks_check(_managed(tmp_path))
    assert code == 1
    assert "- uv is not on PATH, so whether uv.lock answers pyproject.toml cannot be" in output
    assert "run `uv lock --check --offline` yourself" in output


@pytest.mark.parametrize(
    ("declaration", "reason"),
    [
        (None, "never red here: no deployment.json: no deploy tool builds this app"),
        (
            {"unmanaged": True, "reason": "deployed by its owner's own pipeline"},
            "never red here: deployment.json declares this app unmanaged: deployed by its "
            "owner's own pipeline",
        ),
    ],
    ids=["undeclared", "unmanaged"],
)
def test_an_app_no_deploy_tool_builds_is_told_as_a_note(
    tmp_path, monkeypatch, declaration: dict | None, reason: str
) -> None:
    _answers(monkeypatch, uv=1)
    code, output = run_locks_check(_app(tmp_path, declaration, **{"uv.lock": ""}))
    assert code == 0, "an upgrade must not redden a gate over a file the app has not adopted"
    assert output.startswith(verify_module.NOTE_PREFIX)
    assert reason in output.splitlines()[0]
    assert "- uv.lock is missing." in output


def test_a_declaration_that_cannot_be_read_is_held_as_managed(tmp_path, monkeypatch) -> None:
    # Only a file that reads as unmanaged says a tool does not build the app.
    _answers(monkeypatch)
    code, output = run_locks_check(_app(tmp_path, "{not json", **{"uv.lock": ""}))
    assert code == 1
    assert "- uv.lock is missing." in output


def test_an_app_with_nothing_to_lock_passes_with_a_reason(tmp_path) -> None:
    root = project(tmp_path, seed())
    assert run_locks_check(root) == (
        0,
        "no pyproject.toml or frontend/package.json - nothing is locked here",
    )


def test_the_check_is_in_every_profile_and_reached_by_its_own_runner(
    tmp_path, monkeypatch, capsys
) -> None:
    for checks in verify_module.PROFILES.values():
        ids = [check.id for check in checks]
        assert ids.index("deployment") < ids.index("locks") < ids.index("deploy-safety")
    _answers(monkeypatch)
    with pytest.raises(SystemExit) as excinfo:
        main(
            [
                "verify",
                "--root",
                str(_managed(tmp_path)),
                "--only",
                "locks",
                "--format",
                "json",
            ]
        )
    assert excinfo.value.code == 0
    envelope = json.loads(capsys.readouterr().out)
    (result,) = envelope["checks"]
    assert result["id"] == "locks" and result["category"] == "build"
    assert "uv.lock answers pyproject.toml" in result["output_tail"]


# --------------------------------------------------------------------------- #
# the real package managers, offline
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not on PATH")
def test_uv_answers_for_a_lock_it_wrote_and_refuses_it_once_the_manifest_moves(
    tmp_path,
) -> None:
    root = _managed(tmp_path, **{"uv.lock": ""})
    subprocess.run(["uv", "lock", "--offline"], cwd=root, check=True, capture_output=True)  # noqa: S603, S607
    assert run_locks_check(root)[0] == 0

    pyproject = root / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8").replace(
            "dependencies = []", 'dependencies = ["idna>=3.0"]'
        ),
        encoding="utf-8",
    )
    code, output = run_locks_check(root)
    assert code == 1
    assert "- uv.lock is stale against pyproject.toml" in output


@pytest.mark.skipif(shutil.which("npm") is None, reason="npm is not on PATH")
def test_npm_answers_for_a_lock_it_wrote_and_refuses_it_once_the_manifest_moves(
    tmp_path, monkeypatch
) -> None:
    root = _managed(tmp_path, **{"frontend/package.json": _PACKAGE})
    subprocess.run(  # noqa: S603
        [shutil.which("npm") or "npm", "--prefix", "frontend", "install",
         "--package-lock-only", "--offline", "--no-audit", "--no-fund"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    # The backend half is the recorded answer; this case is about npm.
    real = verify_module._run_argv
    monkeypatch.setattr(
        verify_module,
        "_run_argv",
        lambda argv, where, **kwargs: (
            subprocess.CompletedProcess(argv, 0, "", "")
            if argv[0] == "uv"
            else real(argv, where, **kwargs)
        ),
    )
    assert run_locks_check(root)[0] == 0

    package = root / "frontend" / "package.json"
    manifest = json.loads(package.read_text(encoding="utf-8"))
    manifest["dependencies"] = {"is-number": "^7.0.0"}
    package.write_text(json.dumps(manifest), encoding="utf-8")
    code, output = run_locks_check(root)
    assert code == 1
    assert "- frontend/package-lock.json is stale against frontend/package.json" in output
    assert not (root / "frontend" / "node_modules").exists(), "a dry run installs nothing"
