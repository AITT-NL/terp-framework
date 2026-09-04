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
    DEFAULT_API_PORT,
    DEFAULT_WEB_PORT,
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
    backend, frontend = dev_plan(
        app_ref="app.main:app", root=tmp_path, port=8123, web_port=8124
    )

    assert backend.label == "backend"
    assert backend.argv[:4] == (sys.executable, "-m", "uvicorn", "app.main:app")
    assert "--reload" in backend.argv
    assert "8123" in backend.argv
    assert backend.cwd == tmp_path.resolve()

    assert frontend.label == "frontend"
    # The frontend is given its port rather than left to Vite's own 5173.
    assert frontend.argv == ("npm", "run", "dev", "--", "--port", "8124")
    assert frontend.cwd == tmp_path.resolve() / "frontend"


def test_the_frontend_is_told_where_the_backend_actually_is() -> None:
    """The proxy target is derived, not repeated.

    ``vite.config.ts`` falls back to a literal API address, so a moved backend
    port and a stale proxy target would be one edit apart in two repositories --
    and the symptom is a frontend that loads and cannot reach its own API.
    """
    _, frontend = dev_plan(host="127.0.0.5", port=9001)

    assert dict(frontend.env)["TERP_API_PROXY"] == "http://127.0.0.5:9001"


def test_the_default_ports_are_the_range_terp_owns() -> None:
    """8000 and 5173 are where a developer's OTHER applications live.

    Pinned as a test rather than left to the defaults because the whole point of
    the change is that these two numbers agree with the compose files and with
    the workbench's own allocator -- a silent drift back to a conventional port
    is exactly the regression this guards.
    """
    assert (DEFAULT_API_PORT, DEFAULT_WEB_PORT) == (22100, 21100)

    backend, frontend = dev_plan()

    assert str(DEFAULT_API_PORT) in backend.argv
    assert str(DEFAULT_WEB_PORT) in frontend.argv
    assert "8000" not in backend.argv
    assert "5173" not in frontend.argv


def test_a_command_with_no_overlay_inherits_the_environment_untouched() -> None:
    """The backend half declares no overlay, so ``_spawn`` must pass ``env=None``
    rather than a reconstructed copy: a dev server needs PATH, the virtualenv and
    the user's own proxy settings, and rebuilding that dictionary is how one of
    them goes missing."""
    backend, _ = dev_plan()

    assert backend.env == ()


def test_an_overlay_is_layered_over_the_inherited_environment(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other half of the same decision, and the half that has to run a real child.

    ``_spawn`` builds ``{**os.environ, **overlay}`` for a command that declares one, and
    both halves of that expression are load-bearing: the overlay has to WIN for its own
    name -- a developer who exported ``TERP_API_PROXY`` is overruled, because the plan
    knows which port it just chose -- while everything else the parent had survives,
    which is the whole reason it is an overlay rather than a replacement.

    The test above proves the no-overlay half by reading the PLAN, which is why this line
    of ``_spawn`` was the one hole in the coverage gate: nothing ever executed the branch
    that builds the dictionary. Asserted through a real subprocess reporting its own
    environment, because the thing under test IS the environment a child receives -- a
    fake ``Popen`` would only prove a dictionary was built. The child is this interpreter
    writing two values, so there is no server, no port and nothing to clean up.

    Through a FILE rather than a pipe, and that is a fact about the seam rather than a
    preference: ``_spawn`` sets no ``stdout``, because a dev server's output belongs on
    the developer's terminal. So ``communicate()`` hands back ``None`` here and the
    child's report has to land somewhere the test can read.
    """
    monkeypatch.setenv("TERP_API_PROXY", "http://the-developers-own-choice:9000")
    monkeypatch.setenv("TERP_DEV_INHERITED_PROBE", "still here")
    report = tmp_path / "environment.txt"

    command = DevCommand(
        label="probe",
        argv=(
            sys.executable,
            "-c",
            "import os, pathlib, sys; pathlib.Path(sys.argv[1]).write_text("
            "os.environ['TERP_API_PROXY'] + chr(10) "
            "+ os.environ.get('TERP_DEV_INHERITED_PROBE', 'GONE'), encoding='utf-8')",
            str(report),
        ),
        cwd=tmp_path,
        env=(("TERP_API_PROXY", "http://127.0.0.1:22100"),),
    )

    process = _spawn(command)
    assert process.wait(timeout=60) == 0

    overlaid, inherited = report.read_text(encoding="utf-8").splitlines()[:2]
    assert overlaid == "http://127.0.0.1:22100", "the plan's value must beat the exported one"
    assert inherited == "still here", "and everything else the parent had must survive"


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
            "--web-port",
            "9100",
            "--shutdown-timeout",
            "12",
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
        "web_port": 9100,
        "shutdown_timeout": 12,
        "openapi_out": "web/openapi.json",
        "preflight": False,
    }
    assert "terp dev stopped (backend)" in capsys.readouterr().out
