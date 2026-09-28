"""``terp dev`` CLI: the full-stack dev loop — backend + frontend + OpenAPI preflight.

Proves the pure planner computes the uvicorn + npm commands, and that ``run_dev_command``
refreshes the OpenAPI contract, spawns the servers (backend-only when there is no frontend),
and supervises them — all with the spawn/supervise primitives injected so no real server runs.
The real ``_spawn`` / ``_supervise`` / ``_stop`` primitives get their own focused, non-blocking
tests, and one test restarts a real process to prove the stop works on the platform it runs on.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import time

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CLI_SRC = _REPO_ROOT / "packages" / "backend" / "cli" / "src"
sys.path.insert(0, str(_CLI_SRC))

from terp.cli import main, run_dev_command  # noqa: E402
from terp.cli.dev import (  # noqa: E402
    _POLL_SECONDS,
    _refuse_taken_ports,
    DEFAULT_API_PORT,
    DEFAULT_WEB_PORT,
    DevCommand,
    _python_sources,
    _spawn,
    _stop,
    _supervise,
    dev_plan,
    dev_ports,
    reload_paths,
)

_APP_MODULE = """\
from terp.core import create_app

app = create_app([])
"""


def _no_claim(root: pathlib.Path) -> tuple[dict[str, int], str]:
    """No pair claimed, so the machine's real port ledger is never touched here."""
    return {}, ""


def _all_free(port: int) -> bool:
    return True


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
    # terp dev owns the restart (ADR 0156): uvicorn's reloader hangs on Windows when the
    # command was not started from an interactive console.
    assert "--reload" not in backend.argv
    assert "8123" in backend.argv
    assert backend.cwd == tmp_path.resolve()
    assert backend.watch == ()

    assert frontend.label == "frontend"
    # The frontend is given its port rather than left to Vite's own 5173.
    assert frontend.argv == ("npm", "run", "dev", "--", "--port", "8124", "--strictPort")
    assert frontend.cwd == tmp_path.resolve() / "frontend"
    assert frontend.watch == ()  # Vite reloads itself


def test_the_backend_carries_the_paths_that_restart_it(tmp_path: pathlib.Path) -> None:
    watch = (tmp_path / "app", tmp_path / "control_plane")
    backend, frontend = dev_plan(root=tmp_path, watch=watch)
    assert backend.watch == watch
    assert frontend.watch == ()


# --------------------------------------------------------------------------- #
# reload_paths / _python_sources — what a save restarts, and how a change is seen
# --------------------------------------------------------------------------- #
def test_reload_paths_are_the_app_package_and_its_declared_app_packages(
    tmp_path: pathlib.Path,
) -> None:
    for name in ("app", "control_plane", "engine", "frontend"):
        (tmp_path / name).mkdir()
    (tmp_path / "pyproject.toml").write_text(
        '[tool.terp.arch]\napp_packages = ["control_plane"]\ncompanions = ["engine"]\n',
        encoding="utf-8",
    )

    paths = reload_paths("app.main:app", tmp_path)

    # Not the root (node_modules, the virtualenv), and not a companion the API never runs.
    assert paths == (tmp_path.resolve() / "app", tmp_path.resolve() / "control_plane")


def test_a_single_file_app_is_watched_as_its_module_file(tmp_path: pathlib.Path) -> None:
    assert reload_paths("dev_app:app", tmp_path) == (tmp_path.resolve() / "dev_app.py",)


def test_python_sources_see_an_edit_an_addition_and_a_deletion(tmp_path: pathlib.Path) -> None:
    package = tmp_path / "app"
    (package / "sub").mkdir(parents=True)
    (package / "main.py").write_text("x = 1\n", encoding="utf-8")
    (package / "sub" / "models.py").write_text("y = 1\n", encoding="utf-8")
    (package / "notes.txt").write_text("not source\n", encoding="utf-8")
    missing = tmp_path / "absent.py"

    before = _python_sources((package, missing))
    assert set(before) == {str(package / "main.py"), str(package / "sub" / "models.py")}

    time.sleep(0.01)
    (package / "main.py").write_text("x = 2\n", encoding="utf-8")
    edited = _python_sources((package, missing))
    assert edited != before
    (package / "new.py").write_text("z = 1\n", encoding="utf-8")
    assert set(_python_sources((package,))) - set(edited) == {str(package / "new.py")}
    (package / "sub" / "models.py").unlink()
    assert str(package / "sub" / "models.py") not in _python_sources((package,))


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
    supervised: list[tuple[list[DevCommand], object, float]] = []

    def fake_spawn(command: DevCommand) -> _DoneProc:
        return _DoneProc()

    def fake_supervise(commands: object, spawn: object, stop_wait: float) -> None:
        supervised.append((list(commands), spawn, stop_wait))  # type: ignore[call-overload]

    message = run_dev_command(
        app_ref="dev_app:app",
        root=tmp_path,
        spawn=fake_spawn,
        supervise=fake_supervise,
        claim=_no_claim,
        port_free=_all_free,
    )

    # The preflight wrote the live OpenAPI document (the contract's codegen source).
    assert (tmp_path / "openapi.json").exists()
    # The supervisor received both commands, the spawn to start them with, and a stop bound
    # past uvicorn's own graceful-shutdown bound; the backend knows what restarts it.
    [(commands, spawn, stop_wait)] = supervised
    assert [command.label for command in commands] == ["backend", "frontend"]
    assert spawn is fake_spawn
    assert stop_wait == 3 + 5
    assert commands[0].watch == (tmp_path.resolve() / "dev_app.py",)
    assert message == "terp dev stopped (backend + frontend)"
    out = capsys.readouterr().out
    assert "preflight" in out
    assert "restarts when a Python source changes under" in out


def test_run_dev_command_without_frontend_runs_backend_only(tmp_path: pathlib.Path) -> None:
    (tmp_path / "dev_app.py").write_text(_APP_MODULE, encoding="utf-8")
    sys.modules.pop("dev_app", None)
    supervised: list[str] = []

    message = run_dev_command(
        app_ref="dev_app:app",
        root=tmp_path,
        spawn=lambda command: _DoneProc(),
        supervise=lambda commands, spawn, stop_wait: supervised.extend(
            command.label for command in commands
        ),
        claim=_no_claim,
        port_free=_all_free,
    )

    assert supervised == ["backend"]
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
        supervise=lambda commands, spawn, stop_wait: None,
        claim=_no_claim,
        port_free=_all_free,
    )

    assert calls == []
    assert not (tmp_path / "openapi.json").exists()


# --------------------------------------------------------------------------- #
# _spawn / _supervise — the real process primitives
# --------------------------------------------------------------------------- #
def test_spawn_starts_a_real_process(tmp_path: pathlib.Path) -> None:
    process = _spawn(DevCommand("probe", (sys.executable, "-c", "pass"), tmp_path))
    assert process.wait(timeout=30) == 0


class _Proc:
    """A fake dev process: alive until it has answered ``alive_polls`` polls (forever if None)."""

    def __init__(self, label: str, alive_polls: int | None = None) -> None:
        self.label = label
        self._alive = alive_polls
        self.stopped = False

    def poll(self) -> int | None:
        if self.stopped:
            return -15
        if self._alive is None:
            return None
        if self._alive > 0:
            self._alive -= 1
            return None
        return 1


class _Harness:
    """The supervisor's seams, recorded: what was spawned, what was stopped, what was said."""

    def __init__(self, lives: dict[str, list[int | None]], snapshots: list[dict[str, int]]) -> None:
        self._lives = {label: list(values) for label, values in lives.items()}
        self._snapshots = list(snapshots)
        self.spawned: list[_Proc] = []
        self.stopped: list[_Proc] = []
        self.sleeps = 0

    def spawn(self, command: DevCommand) -> _Proc:
        process = _Proc(command.label, self._lives[command.label].pop(0))
        self.spawned.append(process)
        return process

    def stop(self, process: _Proc, wait: float) -> None:
        assert wait == 8.0
        if process.poll() is None:
            self.stopped.append(process)
        process.stopped = True

    def snapshot(self, paths: object) -> dict[str, int]:
        return self._snapshots.pop(0) if len(self._snapshots) > 1 else self._snapshots[0]

    def sleep_then(self, interrupt_after: int | None = None):  # type: ignore[no-untyped-def]
        def sleep(_seconds: float) -> None:
            assert _seconds == _POLL_SECONDS
            self.sleeps += 1
            if interrupt_after is not None and self.sleeps > interrupt_after:
                raise KeyboardInterrupt

        return sleep

    def run(self, commands: list[DevCommand], interrupt_after: int | None = None) -> None:
        _supervise(
            commands,
            self.spawn,  # type: ignore[arg-type]
            8.0,
            stop=self.stop,  # type: ignore[arg-type]
            snapshot=self.snapshot,
            sleep=self.sleep_then(interrupt_after),
        )


_BACKEND = DevCommand("backend", ("uvicorn",), pathlib.Path("."), watch=(pathlib.Path("app"),))
_FRONTEND = DevCommand("frontend", ("npm",), pathlib.Path("frontend"))


def test_the_frontend_exiting_ends_the_session_and_stops_the_backend() -> None:
    harness = _Harness({"backend": [None], "frontend": [1]}, [{"a.py": 1}])

    harness.run([_BACKEND, _FRONTEND])

    backend, frontend = harness.spawned
    assert harness.sleeps == 2  # alive at the first look, gone at the second
    assert harness.stopped == [backend]  # the survivor is stopped, the exited one left alone
    assert not frontend.stopped or frontend.poll() is not None


def test_a_source_change_restarts_the_backend_and_only_the_backend(
    capsys: pytest.CaptureFixture[str],
) -> None:
    harness = _Harness(
        {"backend": [None, None], "frontend": [3]},
        [{"a.py": 1}, {"a.py": 1}, {"a.py": 2}],
    )

    harness.run([_BACKEND, _FRONTEND])

    first, frontend, second = harness.spawned
    assert (first.label, second.label) == ("backend", "backend")
    assert harness.stopped[0] is first  # the old backend is stopped before its successor starts
    assert second in harness.stopped  # and the new one when the session ends
    assert frontend not in harness.stopped
    assert "a source changed; restarting the backend" in capsys.readouterr().out


def test_a_backend_that_dies_waits_for_the_next_save_and_says_so_once(
    capsys: pytest.CaptureFixture[str],
) -> None:
    harness = _Harness(
        {"backend": [0, None], "frontend": [5]},
        [{"a.py": 1}, {"a.py": 1}, {"a.py": 1}, {"a.py": 1}, {"a.py": 2}],
    )

    harness.run([_BACKEND, _FRONTEND])

    out = capsys.readouterr().out
    assert out.count("the backend exited; it restarts at the next save") == 1
    assert [process.label for process in harness.spawned] == ["backend", "frontend", "backend"]
    assert "restarting the backend" in out


def test_ctrl_c_is_an_ordinary_stop_that_takes_every_process_with_it() -> None:
    harness = _Harness({"backend": [None], "frontend": [None]}, [{"a.py": 1}])

    harness.run([_BACKEND, _FRONTEND], interrupt_after=2)  # returns; KeyboardInterrupt absorbed

    assert sorted(process.label for process in harness.stopped) == ["backend", "frontend"]


class _StopProbe:
    """Records what ``_stop`` does to a process."""

    def __init__(self, exited: bool = False, times_out: bool = False) -> None:
        self.pid = 4242
        self._exited = exited
        self._times_out = times_out
        self.calls: list[object] = []

    def poll(self) -> int | None:
        return 0 if self._exited else None

    def terminate(self) -> None:
        self.calls.append("terminate")

    def kill(self) -> None:
        self.calls.append("kill")

    def wait(self, timeout: float | None = None) -> int:
        self.calls.append(("wait", timeout))
        if self._times_out and timeout is not None:
            raise subprocess.TimeoutExpired("uvicorn", timeout)
        return 0


def test_stop_leaves_an_exited_process_alone() -> None:
    probe = _StopProbe(exited=True)
    _stop(probe, 8.0, platform="linux", run=lambda *a, **k: None)  # type: ignore[arg-type]
    assert probe.calls == []


def test_stop_takes_the_whole_tree_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SystemRoot", "C:\\Windows")
    ran: list[list[str]] = []
    probe = _StopProbe()

    _stop(probe, 8.0, platform="win32", run=lambda argv, **kwargs: ran.append(argv))  # type: ignore[arg-type]

    [argv] = ran
    assert pathlib.Path(argv[0]).name == "taskkill.exe"
    assert argv[1:] == ["/PID", "4242", "/T", "/F"]
    assert probe.calls == [("wait", 8.0)]  # no terminate: it would take the root alone


def test_stop_sends_sigterm_elsewhere_and_kills_what_outlives_the_bound() -> None:
    graceful = _StopProbe()
    _stop(graceful, 8.0, platform="linux")  # type: ignore[arg-type]
    assert graceful.calls == ["terminate", ("wait", 8.0)]

    stubborn = _StopProbe(times_out=True)
    _stop(stubborn, 8.0, platform="linux")  # type: ignore[arg-type]
    assert stubborn.calls == ["terminate", ("wait", 8.0), "kill", ("wait", None)]


def _is_running(pid: int) -> bool:
    """Whether *pid* is a live process, asked without signalling it."""
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        kernel32.CloseHandle(handle)
        return code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_a_real_process_is_restarted_and_stopped(tmp_path: pathlib.Path) -> None:
    """The real supervisor, spawn and stop on this platform, with a real file edit.

    A child that would run for a minute stands in for uvicorn. The watched file is edited
    after the first look, so the supervisor must stop the child (``taskkill /T`` on Windows,
    SIGTERM elsewhere) and start another; Ctrl+C then ends the session and stops that one.

    Each child records the pid of the interpreter that actually runs it, and those are what
    must be gone. On Windows the child is started the way ``npm`` is — through ``cmd.exe`` —
    because that is the tree a root-only stop gets wrong: ``cmd.exe`` dies, ``poll()`` is
    satisfied, and the process beneath it goes on running.
    """
    shell = ("cmd", "/c") if sys.platform == "win32" else ()
    source = tmp_path / "main.py"
    source.write_text("x = 1\n", encoding="utf-8")
    pids = tmp_path / "pids"
    pids.mkdir()
    command = DevCommand(
        "backend",
        (
            *shell,
            sys.executable,
            "-c",
            "import os, pathlib, sys, time; "
            "(pathlib.Path(sys.argv[1]) / str(os.getpid())).touch(); time.sleep(60)",
            str(pids),
        ),
        tmp_path,
        watch=(source,),
    )
    started: list[subprocess.Popen[bytes]] = []
    looks = 0

    def spawn(planned: DevCommand) -> subprocess.Popen[bytes]:
        started.append(_spawn(planned))
        return started[-1]

    def recorded(count: int) -> list[int]:
        deadline = time.monotonic() + 30
        while len(list(pids.iterdir())) < count and time.monotonic() < deadline:
            time.sleep(0.05)
        return [int(path.name) for path in pids.iterdir()]

    def sleep(_seconds: float) -> None:
        nonlocal looks
        looks += 1
        if looks == 1:
            recorded(1)  # the first child is running before its source changes
            source.write_text("x = 2\n", encoding="utf-8")
            os.utime(source, ns=(time.time_ns(), time.time_ns() + 10**9))
        elif looks == 2:
            recorded(2)
        else:
            raise KeyboardInterrupt

    _supervise([command], spawn, 10.0, sleep=sleep)

    assert len(started) == 2
    interpreters = recorded(2)
    assert len(interpreters) == 2
    assert not [pid for pid in interpreters if _is_running(pid)]



# --------------------------------------------------------------------------- #
# dev_ports — the checkout's own host ports
# --------------------------------------------------------------------------- #
def test_the_claimed_pair_is_used_when_nothing_is_passed(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Editor, workbench and compose all read one claim, so they land on one pair."""
    claimed: list[pathlib.Path] = []

    def claim(root: pathlib.Path) -> tuple[dict[str, int], str]:
        claimed.append(root)
        return {"WEB_PORT": 21107, "API_PORT": 22107}, "terp ports: assigned API_PORT=22107, WEB_PORT=21107"

    (api, web) = dev_ports(tmp_path, port=None, web_port=None, claim=claim)

    assert claimed == [tmp_path]
    assert api == (22107, "API_PORT, claimed for this checkout")
    assert web == (21107, "WEB_PORT, claimed for this checkout")
    assert "assigned API_PORT=22107" in capsys.readouterr().out  # the claim's note is shown


def test_an_explicit_port_wins_and_the_other_half_is_still_claimed(
    tmp_path: pathlib.Path,
) -> None:
    claim = lambda root: ({"WEB_PORT": 21107, "API_PORT": 22107}, "")  # noqa: E731

    (api, web) = dev_ports(tmp_path, port=9000, web_port=None, claim=claim)

    assert api == (9000, "from --port")
    assert web == (21107, "WEB_PORT, claimed for this checkout")


def test_both_ports_passed_means_no_claim_is_made(tmp_path: pathlib.Path) -> None:
    def claim(root: pathlib.Path) -> tuple[dict[str, int], str]:
        raise AssertionError("an explicit pair must not claim or publish anything")

    assert dev_ports(tmp_path, port=9000, web_port=9001, claim=claim) == (
        (9000, "from --port"),
        (9001, "from --web-port"),
    )


def test_no_claim_falls_back_to_the_fixed_pair_and_says_why(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    claim = lambda root: ({}, "workbench.json declares this app unmanaged")  # noqa: E731

    (api, web) = dev_ports(tmp_path, port=None, web_port=None, claim=claim)

    assert (api[0], web[0]) == (DEFAULT_API_PORT, DEFAULT_WEB_PORT)
    assert "no pair could be claimed" in api[1]
    assert "unmanaged" in capsys.readouterr().out


def test_the_names_a_workbench_declares_are_the_names_read(tmp_path: pathlib.Path) -> None:
    """An app that publishes its ports as other names is read by those names."""
    (tmp_path / "workbench.json").write_text(
        '{"schemaVersion": 1, "compose": {"file": "docker-compose.yml"}, "services": ['
        '{"role": "web", "service": "web", "hostPortEnv": "SHOP_WEB_PORT"},'
        '{"role": "api", "service": "api", "hostPortEnv": "SHOP_API_PORT"}]}',
        encoding="utf-8",
    )
    claim = lambda root: ({"SHOP_WEB_PORT": 21120, "SHOP_API_PORT": 22120}, "")  # noqa: E731

    (api, web) = dev_ports(tmp_path, port=None, web_port=None, claim=claim)

    assert (api[0], web[0]) == (22120, 21120)


def test_a_taken_port_stops_the_start_and_names_both_ways_out() -> None:
    with pytest.raises(SystemExit) as refused:
        _refuse_taken_ports(
            [("backend", 22107, "API_PORT, claimed for this checkout"), ("frontend", 21107, "x")],
            port_free=lambda port: port != 22107,
        )
    message = str(refused.value)
    assert "backend: 22107 (API_PORT, claimed for this checkout)" in message
    assert "frontend" not in message.split("\n", 1)[1].split("\n")[0]  # only the taken one
    assert "terp ports assign --reassign" in message
    _refuse_taken_ports([("backend", 1, "x")], port_free=lambda port: True)  # free: no raise


def test_run_dev_command_refuses_before_starting_anything(tmp_path: pathlib.Path) -> None:
    started: list[object] = []

    with pytest.raises(SystemExit):
        run_dev_command(
            app_ref="app.main:app",
            root=tmp_path,
            preflight=False,
            spawn=lambda command: started.append(command) or _DoneProc(),
            supervise=lambda commands, spawn, stop_wait: started.append(commands),
            claim=lambda root: ({"WEB_PORT": 21107, "API_PORT": 22107}, ""),
            port_free=lambda port: False,
        )

    assert started == []


def test_the_frontend_port_is_only_checked_when_there_is_a_frontend(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    checked: list[int] = []
    run_dev_command(
        app_ref="app.main:app",
        root=tmp_path,
        preflight=False,
        spawn=lambda command: _DoneProc(),
        supervise=lambda commands, spawn, stop_wait: None,
        claim=lambda root: ({"WEB_PORT": 21107, "API_PORT": 22107}, ""),
        port_free=lambda port: checked.append(port) or True,
    )
    assert checked == [22107]
    out = capsys.readouterr().out
    assert "backend on http://127.0.0.1:22107 (API_PORT, claimed for this checkout)" in out
    assert "frontend on" not in out

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


def test_cli_dev_leaves_the_ports_to_the_checkouts_claim(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """No flag means no number: a fixed default here would outrank the claim."""
    captured: dict[str, object] = {}

    def fake_run(**kwargs: object) -> str:
        captured.update(kwargs)
        return "terp dev stopped (backend)"

    monkeypatch.setattr("terp.cli.run_dev_command", fake_run)
    main(["dev", "--no-preflight"])

    assert (captured["port"], captured["web_port"]) == (None, None)
