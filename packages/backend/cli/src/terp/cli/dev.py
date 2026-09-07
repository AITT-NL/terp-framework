"""``terp dev`` — run the backend and frontend dev servers together (with the codegen preflight).

The full-stack dev loop of design §7: one command boots the API (uvicorn ``--reload``) and the
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

from terp.cli.openapi import export_openapi
from terp.cli.routes import run_routes_command

_POLL_SECONDS = 0.2

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
#: has always allocated its per-project ports out of this range. The compose
#: files carry the same two numbers as their ``${WEB_PORT:-...}`` fallbacks, so
#: the two ways to run an app agree on where to answer.
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


def dev_plan(
    *,
    app_ref: str = "app.main:app",
    root: str | pathlib.Path = ".",
    frontend_dir: str = "frontend",
    host: str = "127.0.0.1",
    port: int = DEFAULT_API_PORT,
    web_port: int = DEFAULT_WEB_PORT,
    shutdown_timeout: int = SHUTDOWN_TIMEOUT_SECONDS,
) -> tuple[DevCommand, DevCommand]:
    """Pure: the ``(backend, frontend)`` commands ``terp dev`` runs.

    Backend = ``uvicorn <app_ref> --reload`` from the project root; frontend = ``npm run dev``
    from ``<root>/<frontend_dir>`` (the copier template + example layout). The frontend command
    is returned unconditionally; the executor runs it only when its directory exists.

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
            "--reload",
            "--host",
            host,
            "--port",
            str(port),
            "--timeout-graceful-shutdown",
            str(shutdown_timeout),
        ),
        cwd=root_path,
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
Supervise = Callable[[Sequence["subprocess.Popen[bytes]"]], None]


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


def _supervise(
    processes: Sequence[subprocess.Popen[bytes]],
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Block until one process exits, then terminate the rest (a crash or Ctrl+C stops both)."""
    while all(process.poll() is None for process in processes):
        sleep(_POLL_SECONDS)
    for process in processes:
        if process.poll() is None:
            process.terminate()


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
    uvicorn (``--reload``) and the frontend dev server then run side by side until one exits or is
    interrupted, when the other is stopped too. A repo without ``<frontend_dir>/`` runs backend-only.

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
    )
    if preflight:
        destination = export(app_ref, out=root_path / openapi_out, app_root=root_path)
        print(f"terp dev — OpenAPI preflight wrote {destination}")
        # Offered, not imposed: an app that has not adopted route types (no `routes`
        # script) is skipped with the hint, so upgrading the framework never breaks
        # `terp dev`. A wired app's generator failure IS surfaced — it is the author's
        # own manifest that cannot be read.
        summary = regenerate_routes(
            root=root_path, frontend_dir=frontend_dir, optional=True
        )
        print(f"terp dev — routes preflight: {summary}")

    commands = [backend]
    if frontend.cwd.is_dir():
        commands.append(frontend)
    for command in commands:
        print(f"  {command.label:8} → {' '.join(command.argv)}  (cwd {command.cwd})")

    processes = [spawn(command) for command in commands]
    supervise(processes)
    ran = " + ".join(command.label for command in commands)
    return f"terp dev stopped ({ran})"


__all__ = [
    "DEFAULT_API_PORT",
    "DEFAULT_WEB_PORT",
    "DevCommand",
    "dev_plan",
    "run_dev_command",
]
