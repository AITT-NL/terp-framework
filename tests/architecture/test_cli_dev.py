"""``terp dev`` CLI: the full-stack dev loop — backend + frontend + OpenAPI preflight.

Proves the pure planner computes the uvicorn + npm commands, and that ``run_dev_command``
refreshes the OpenAPI contract, spawns the servers (backend-only when there is no frontend),
and supervises them — all with the spawn/supervise primitives injected so no real server runs.
The real ``_spawn`` / ``_supervise`` primitives get their own focused, non-blocking tests.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CLI_SRC = _REPO_ROOT / "packages" / "backend" / "cli" / "src"
sys.path.insert(0, str(_CLI_SRC))

from terp.cli import main, run_dev_command  # noqa: E402
from terp.cli.dev import (  # noqa: E402
    _POLL_SECONDS,
    DevCommand,
    _spawn,
    _supervise,
    dev_plan,
)

_APP_MODULE = """\
from terp.core import create_app

app = create_app([])
"""


class _DoneProc:
    """A fake process that has already exited (for the spawn/supervise seams)."""

    def poll(self) -> int:
        return 0


# --------------------------------------------------------------------------- #
# dev_plan — the pure command planner
# --------------------------------------------------------------------------- #
def test_dev_plan_builds_backend_and_frontend_commands(tmp_path: pathlib.Path) -> None:
    backend, frontend = dev_plan(app_ref="app.main:app", root=tmp_path, port=8123)

    assert backend.label == "backend"
    assert backend.argv[:4] == (sys.executable, "-m", "uvicorn", "app.main:app")
    assert "--reload" in backend.argv
    assert "8123" in backend.argv
    assert backend.cwd == tmp_path.resolve()

    assert frontend.label == "frontend"
    assert frontend.argv == ("npm", "run", "dev")
    assert frontend.cwd == tmp_path.resolve() / "frontend"


# --------------------------------------------------------------------------- #
# run_dev_command — preflight + spawn + supervise
# --------------------------------------------------------------------------- #
def test_run_dev_command_preflights_spawns_and_supervises(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "dev_app.py").write_text(_APP_MODULE, encoding="utf-8")
    (tmp_path / "frontend").mkdir()
    sys.modules.pop("dev_app", None)
    spawned: list[DevCommand] = []
    supervised: list[list[object]] = []

    def fake_spawn(command: DevCommand) -> _DoneProc:
        spawned.append(command)
        return _DoneProc()

    def fake_supervise(processes: object) -> None:
        supervised.append(list(processes))  # type: ignore[arg-type]

    message = run_dev_command(
        app_ref="dev_app:app", root=tmp_path, spawn=fake_spawn, supervise=fake_supervise
    )

    # The preflight wrote the live OpenAPI document (the contract's codegen source).
    assert (tmp_path / "openapi.json").exists()
    # Both servers were spawned, and the supervisor received exactly those processes.
    assert [command.label for command in spawned] == ["backend", "frontend"]
    assert len(supervised) == 1 and len(supervised[0]) == 2
    assert message == "terp dev stopped (backend + frontend)"
    assert "preflight" in capsys.readouterr().out


def test_run_dev_command_without_frontend_runs_backend_only(tmp_path: pathlib.Path) -> None:
    (tmp_path / "dev_app.py").write_text(_APP_MODULE, encoding="utf-8")
    sys.modules.pop("dev_app", None)
    spawned: list[DevCommand] = []

    message = run_dev_command(
        app_ref="dev_app:app",
        root=tmp_path,
        spawn=lambda command: spawned.append(command) or _DoneProc(),
        supervise=lambda processes: None,
    )

    assert [command.label for command in spawned] == ["backend"]
    assert message == "terp dev stopped (backend)"


def test_run_dev_command_no_preflight_skips_export(tmp_path: pathlib.Path) -> None:
    calls: list[object] = []

    def recording_export(*args: object, **kwargs: object) -> pathlib.Path:
        calls.append((args, kwargs))
        return tmp_path / "unused.json"

    run_dev_command(
        app_ref="app.main:app",
        root=tmp_path,
        preflight=False,
        export=recording_export,
        spawn=lambda command: _DoneProc(),
        supervise=lambda processes: None,
    )

    assert calls == []
    assert not (tmp_path / "openapi.json").exists()


# --------------------------------------------------------------------------- #
# _spawn / _supervise — the real process primitives
# --------------------------------------------------------------------------- #
def test_spawn_starts_a_real_process(tmp_path: pathlib.Path) -> None:
    process = _spawn(DevCommand("probe", (sys.executable, "-c", "pass"), tmp_path))
    assert process.wait(timeout=30) == 0


class _FakeProc:
    """Alive for ``alive_polls`` poll()s, then exited; records terminate()."""

    def __init__(self, alive_polls: int) -> None:
        self._alive = alive_polls
        self.terminated = False

    def poll(self) -> int | None:
        if self._alive > 0:
            self._alive -= 1
            return None
        return 0

    def terminate(self) -> None:
        self.terminated = True


def test_supervise_waits_then_terminates_peers() -> None:
    slept: list[float] = []
    first = _FakeProc(alive_polls=1)  # reports running once, then exits
    peer = _FakeProc(alive_polls=99)  # still running when the first exits

    _supervise([first, peer], sleep=slept.append)  # type: ignore[list-item]

    assert slept == [_POLL_SECONDS]  # looped once while both were alive
    assert peer.terminated  # the surviving peer is stopped
    assert not first.terminated  # the one that exited is left alone


# --------------------------------------------------------------------------- #
# main() dispatch
# --------------------------------------------------------------------------- #
def test_cli_dev_dispatch(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    def fake_run(**kwargs: object) -> str:
        captured.update(kwargs)
        return "terp dev stopped (backend)"

    monkeypatch.setattr("terp.cli.run_dev_command", fake_run)
    main(
        [
            "dev",
            "--app",
            "pkg.main:app",
            "--app-root",
            "proj",
            "--frontend-dir",
            "web",
            "--host",
            "127.0.0.9",
            "--port",
            "9000",
            "--openapi-out",
            "web/openapi.json",
            "--no-preflight",
        ]
    )

    assert captured == {
        "app_ref": "pkg.main:app",
        "root": "proj",
        "frontend_dir": "web",
        "host": "127.0.0.9",
        "port": 9000,
        "openapi_out": "web/openapi.json",
        "preflight": False,
    }
    assert "terp dev stopped (backend)" in capsys.readouterr().out
