"""``terp dev`` — run the backend and frontend dev servers together (with the codegen preflight).

The full-stack dev loop of design §7: one command boots the API (uvicorn, restarted by this command
when a Python source of the app changes) and the
frontend dev server side by side, after refreshing both derived frontend artifacts — the OpenAPI
document the typed client is generated from, and the route types extracted from the module
manifests (ADR 0092) — so a route or endpoint added a minute ago is current before the servers
start. A repo with no ``frontend/`` directory (a backend-only app) runs just the API server.

The command is a pure planner (:func:`dev_plan`, which computes the two process commands) plus a
thin executor (:func:`run_dev_command`) with the process spawn/supervise primitives injected, so
the orchestration is fully testable without launching real servers.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from terp.cli._output import emit
from terp.cli.openapi import export_openapi
from terp.cli.routes import run_routes_command

#: Seconds between two looks at the servers and at the backend's sources. The source scan runs on
#: every look, so this is also how long an edit can wait before the backend restarts.
_POLL_SECONDS = 0.5

#: Seconds allowed past the backend's own graceful-shutdown bound before a process is killed.
_STOP_MARGIN_SECONDS = 5

#: Seconds uvicorn waits for in-flight work before cancelling it, at shutdown.
#:
#: Unset, uvicorn waits forever, and "forever" is the literal outcome for an app serving a
#: realtime channel: an SSE or WebSocket stream is a task that ends when the client goes away
#: and not otherwise, so one open browser tab holds the reload loop until someone kills the
#: process by hand. The reload loop pays this cost on every backend edit, which is why the
#: bound here is shorter than the one the served images carry (ADR 0108): a dev request that
#: needs more than three seconds is not worth holding the restart for.
SHUTDOWN_TIMEOUT_SECONDS = 3


#: Default host ports for ``terp dev``, in the range Terp owns.
#:
#: Not 8000 and 5173. Those are where a developer's OTHER applications live, so
#: defaulting there means the framework's own dev loop is the thing that collides
#: with the rest of the machine -- and it collided with the workbench too, which
#: has always allocated its per-project ports out of this range. The example
#: app's compose file carries the same two numbers as its ``${WEB_PORT:-...}``
#: fallbacks. The template's has no fallback at all: it requires a pair claimed
#: by ``terp ports assign``, so two checkouts cannot land on one port.
#:
#: The container-internal ports are deliberately NOT these: inside the Compose
#: network 8000 and 5173 cannot collide with anything, and moving them would
#: churn every healthcheck and proxy target for no gain.
DEFAULT_API_PORT = 22100
DEFAULT_WEB_PORT = 21100


@dataclass(frozen=True)
class DevCommand:
    """One dev process: a label, the argv to launch, its cwd, and its env overlay."""

    label: str
    argv: tuple[str, ...]
    cwd: pathlib.Path
    #: Variables layered over the inherited environment for this process only.
    #: A tuple of pairs rather than a dict so the dataclass stays frozen and
    #: comparable, which is what lets a test assert the whole command.
    env: tuple[tuple[str, str], ...] = ()
    #: Paths whose Python sources restart this process when one changes. Empty for a process
    #: that reloads itself: Vite has its own hot module replacement.
    watch: tuple[pathlib.Path, ...] = ()


def dev_plan(
    *,
    app_ref: str = "app.main:app",
    root: str | pathlib.Path = ".",
    frontend_dir: str = "frontend",
    host: str = "127.0.0.1",
    port: int = DEFAULT_API_PORT,
    web_port: int = DEFAULT_WEB_PORT,
    shutdown_timeout: int = SHUTDOWN_TIMEOUT_SECONDS,
    watch: Sequence[pathlib.Path] = (),
) -> tuple[DevCommand, DevCommand]:
    """Pure: the ``(backend, frontend)`` commands ``terp dev`` runs.

    Backend = ``uvicorn <app_ref>`` from the project root, restarted by the supervisor when a
    Python source under *watch* changes; frontend = ``npm run dev`` from
    ``<root>/<frontend_dir>`` (the copier template + example layout). The frontend command
    is returned unconditionally; the executor runs it only when its directory exists.

    **Not ``--reload``.** uvicorn's reloader restarts its worker on Windows by sending it a
    console Ctrl+C and then waiting for it to exit, with no bound. Started from anything that
    is not an interactive console — an agent's shell tool, an editor task, a workbench — that
    signal never stopped the worker: the reloader logged "Reloading..." and waited forever,
    and the old code went on answering every request. Reproduced on every edit, and the flags
    that would give the worker a console of its own did not change it. So this command owns
    the restart instead (ADR 0156), and stops the process by a means that needs no console.

    The backend argv carries an explicit ``--timeout-graceful-shutdown``: an app serving a
    realtime channel has tasks that never end on their own, and uvicorn's own default is to
    wait for them indefinitely (ADR 0108). This is the one invocation an app cannot edit —
    the compose files and images are its own — so *shutdown_timeout* is the escape, surfaced
    as ``terp dev --shutdown-timeout``. A non-positive value is refused rather than passed
    through: uvicorn reads ``0`` as "cancel in-flight work immediately", which is a different
    decision from the one this argument names, and a negative one is meaningless.

    Both host ports are explicit, and the frontend is TOLD where the backend is rather than
    left to assume. ``vite.config.ts`` falls back to a literal API address when
    ``TERP_API_PROXY`` is unset, so a moved backend port and a stale proxy target would be one
    edit apart in two repositories -- and that failure is a frontend which loads and cannot
    reach its own API. Passing the value removes the second copy: the proxy target is derived
    from the port this command actually binds.
    """
    if shutdown_timeout <= 0:
        raise ValueError(
            f"shutdown_timeout must be a positive number of seconds, got {shutdown_timeout}"
        )
    root_path = pathlib.Path(root).resolve()
    backend = DevCommand(
        label="backend",
        argv=(
            sys.executable,
            "-m",
            "uvicorn",
            app_ref,
            "--host",
            host,
            "--port",
            str(port),
            "--timeout-graceful-shutdown",
            str(shutdown_timeout),
        ),
        cwd=root_path,
        watch=tuple(watch),
    )
    frontend = DevCommand(
        label="frontend",
        # ``--`` separates npm's own arguments from the script's. Vite defaults to
        # 5173 and the template config pins nothing, so without this the frontend
        # half of the dev loop lands on the very port the rest of this change
        # moves away from.
        argv=("npm", "run", "dev", "--", "--port", str(web_port)),
        cwd=root_path / frontend_dir,
        env=(("TERP_API_PROXY", f"http://{host}:{port}"),),
    )
    return backend, frontend


Spawn = Callable[[DevCommand], "subprocess.Popen[bytes]"]
#: Runs the planned commands until the session ends: ``(commands, spawn, stop_wait)``.
Supervise = Callable[[Sequence[DevCommand], Spawn, float], None]
Stop = Callable[["subprocess.Popen[bytes]", float], None]
Snapshot = Callable[[Sequence[pathlib.Path]], dict[str, int]]


def reload_paths(app_ref: str, root: str | pathlib.Path = ".") -> tuple[pathlib.Path, ...]:
    """The paths whose Python sources restart the backend.

    The app's own package — the first segment of *app_ref*, as a directory, or as a module
    file for a single-file app — and every package ``[tool.terp.arch] app_packages`` declares
    as more of the application (ADR 0141). That is one declaration of what the app is, so the
    scope the gate scans is the scope a save restarts.

    Not the project root, which is what ``uvicorn --reload`` watched: that tree holds the
    frontend's ``node_modules`` and the virtualenv, neither of them the API's source. Not a
    declared companion either: ``create_app`` does not mount one, so the API never runs it.
    """
    from terp.arch import RootKind, declared_roots

    root_path = pathlib.Path(root).resolve()
    own = root_path / app_ref.split(":", 1)[0].split(".", 1)[0]
    paths = [own if own.is_dir() else own.with_suffix(".py")]
    paths += [scan.path for scan in declared_roots(root_path) if scan.kind is RootKind.APP]
    return tuple(paths)


def _python_sources(paths: Sequence[pathlib.Path]) -> dict[str, int]:
    """Every Python source under *paths*, with its modification time.

    Two of these compared tell a new file, a deleted one and an edited one apart from no
    change at all, and each of the three means the running backend no longer matches its
    source. A stat walk rather than an OS watcher: the paths are the app's own packages, and
    a walk has no dependency and no platform-specific behaviour to get wrong.
    """
    found: dict[str, int] = {}
    for path in paths:
        for source in path.rglob("*.py") if path.is_dir() else (path,):
            try:
                found[str(source)] = source.stat().st_mtime_ns
            except FileNotFoundError:
                # Absent: a single-file app not written yet, or a file deleted between being
                # listed and being read. Either way the next look sees the settled state.
                continue
    return found


def _spawn(command: DevCommand) -> subprocess.Popen[bytes]:
    """Start one dev process, resolving its executable on PATH (so ``npm`` works on Windows)."""
    executable = shutil.which(command.argv[0]) or command.argv[0]
    # Layered over the inherited environment rather than replacing it: a dev server
    # needs PATH, the virtualenv, the user's proxy settings and their terminal
    # locale, and only an overlay keeps them. ``os.environ`` is read first, so a
    # developer who has exported TERP_API_PROXY to point somewhere else is
    # overruled -- which is wrong the other way round, and is why the overlay is
    # applied ONLY for names the plan actually sets.
    env = None
    if command.env:
        env = {**os.environ, **dict(command.env)}
    # The argv is an internally composed dev command (uvicorn / npm from dev_plan), run with
    # shell=False, so there is no shell interpolation of untrusted input.
    return subprocess.Popen(  # noqa: S603 - internal dev argv, shell=False (no injection)
        (executable, *command.argv[1:]), cwd=command.cwd, env=env
    )


def _stop(
    process: subprocess.Popen[bytes],
    wait_seconds: float,
    *,
    platform: str = sys.platform,
    run: Callable[..., object] = subprocess.run,
) -> None:
    """Stop one dev process and everything it started, and wait until it has.

    On Windows ``npm`` resolves to ``npm.cmd``, so the frontend process ``terp dev`` starts is
    ``cmd.exe`` and Vite runs in a node process beneath it. Terminating ``cmd.exe`` leaves that
    node process running and holding the port (measured), so the next ``terp dev`` cannot
    bind it. ``taskkill /T /F`` ends the whole tree and needs no console, which is the property
    uvicorn's own restart lacked. It is not graceful: on a development machine a restart that
    happens is worth more than a lifespan hook's clean exit. Elsewhere SIGTERM reaches the
    process that holds the port, and uvicorn shuts down within its own graceful bound.

    A process still running after *wait_seconds* is killed outright.
    """
    if process.poll() is not None:
        return
    if platform == "win32":
        system_root = pathlib.Path(os.environ.get("SystemRoot", "C:\\Windows"))
        taskkill = system_root / "System32" / "taskkill.exe"
        run([str(taskkill), "/PID", str(process.pid), "/T", "/F"], capture_output=True, check=False)
    else:
        process.terminate()
    try:
        process.wait(timeout=wait_seconds)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _supervise(
    commands: Sequence[DevCommand],
    spawn: Spawn,
    stop_wait: float,
    *,
    stop: Stop = _stop,
    snapshot: Snapshot = _python_sources,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Run *commands* until one that does not restart itself exits, or until Ctrl+C.

    A command with ``watch`` paths is restarted when a Python source under them changes. When
    it exits on its own it is waited for, not given up on: a save that leaves a module half
    written makes uvicorn fail to import, and the next save should bring it back, which is
    what ``--reload`` did. Any other command exiting ends the session. Ctrl+C ends it too, as
    the ordinary way to stop, and every process is stopped on the way out however the session
    ends.
    """
    running = {command: spawn(command) for command in commands}
    seen = {command: snapshot(command.watch) for command in commands if command.watch}
    waiting: set[DevCommand] = set()
    try:
        while True:
            sleep(_POLL_SECONDS)
            for command, process in list(running.items()):
                if not command.watch:
                    if process.poll() is not None:
                        return
                    continue
                current = snapshot(command.watch)
                if current != seen[command]:
                    seen[command] = current
                    waiting.discard(command)
                    emit(f"terp dev — a source changed; restarting the {command.label}")
                    stop(process, stop_wait)
                    running[command] = spawn(command)
                elif process.poll() is not None and command not in waiting:
                    waiting.add(command)
                    emit(f"terp dev — the {command.label} exited; it restarts at the next save")
    except KeyboardInterrupt:
        return
    finally:
        for process in running.values():
            stop(process, stop_wait)


def run_dev_command(
    *,
    app_ref: str = "app.main:app",
    root: str | pathlib.Path = ".",
    frontend_dir: str = "frontend",
    host: str = "127.0.0.1",
    port: int = DEFAULT_API_PORT,
    web_port: int = DEFAULT_WEB_PORT,
    shutdown_timeout: int = SHUTDOWN_TIMEOUT_SECONDS,
    openapi_out: str = "openapi.json",
    preflight: bool = True,
    export: Callable[..., pathlib.Path] = export_openapi,
    regenerate_routes: Callable[..., str] = run_routes_command,
    spawn: Spawn = _spawn,
    supervise: Supervise = _supervise,
) -> str:
    """Run the backend + frontend dev servers together, after the codegen preflight.

    The preflight regenerates both derived artifacts so the frontend is current before the servers
    start: the live app's OpenAPI document (the typed client's codegen source) and — when the repo
    has a frontend — the route types extracted from the module manifests (ADR 0092), so a route
    added a minute ago is navigable and checked. Pass ``preflight=False`` to skip both.
    uvicorn and the frontend dev server then run side by side: the backend is restarted when a
    Python source of the app changes (:func:`reload_paths`), and the session ends when the
    frontend exits or on Ctrl+C, stopping both. A repo without ``<frontend_dir>/`` runs
    backend-only.

    *export* / *regenerate_routes* / *spawn* / *supervise* are injected so the orchestration is
    testable without launching real servers. Returns a one-line summary of what was stopped.
    """
    root_path = pathlib.Path(root).resolve()
    backend, frontend = dev_plan(
        app_ref=app_ref,
        root=root_path,
        frontend_dir=frontend_dir,
        host=host,
        port=port,
        web_port=web_port,
        shutdown_timeout=shutdown_timeout,
        watch=reload_paths(app_ref, root_path),
    )
    if preflight:
        destination = export(app_ref, out=root_path / openapi_out, app_root=root_path)
        emit(f"terp dev — OpenAPI preflight wrote {destination}")
        # Offered, not imposed: an app that has not adopted route types (no `routes`
        # script) is skipped with the hint, so upgrading the framework never breaks
        # `terp dev`. A wired app's generator failure IS surfaced — it is the author's
        # own manifest that cannot be read.
        summary = regenerate_routes(
            root=root_path, frontend_dir=frontend_dir, optional=True
        )
        emit(f"terp dev — routes preflight: {summary}")

    commands = [backend]
    if frontend.cwd.is_dir():
        commands.append(frontend)
    for command in commands:
        emit(f"  {command.label:8} → {' '.join(command.argv)}  (cwd {command.cwd})")

    emit(
        "terp dev — the backend restarts when a Python source changes under "
        + ", ".join(str(path) for path in backend.watch)
    )
    supervise(commands, spawn, shutdown_timeout + _STOP_MARGIN_SECONDS)
    ran = " + ".join(command.label for command in commands)
    return f"terp dev stopped ({ran})"


__all__ = [
    "DEFAULT_API_PORT",
    "DEFAULT_WEB_PORT",
    "DevCommand",
    "dev_plan",
    "reload_paths",
    "run_dev_command",
]
