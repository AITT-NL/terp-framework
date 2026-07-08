"""``terp dev`` — run the backend and frontend dev servers together (with an OpenAPI preflight).

The full-stack dev loop of design §7: one command boots the API (uvicorn ``--reload``) and the
frontend dev server side by side, after refreshing the OpenAPI document the frontend contract is
generated from — so the typed client's source is current before the servers start. A repo with no
``frontend/`` directory (a backend-only app) runs just the API server.

The command is a pure planner (:func:`dev_plan`, which computes the two process commands) plus a
thin executor (:func:`run_dev_command`) with the process spawn/supervise primitives injected, so
the orchestration is fully testable without launching real servers.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from terp.cli.openapi import export_openapi

_POLL_SECONDS = 0.2


@dataclass(frozen=True)
class DevCommand:
    """One dev process: a label, the argv to launch, and its working directory."""

    label: str
    argv: tuple[str, ...]
    cwd: pathlib.Path


def dev_plan(
    *,
    app_ref: str = "app.main:app",
    root: str | pathlib.Path = ".",
    frontend_dir: str = "frontend",
    host: str = "127.0.0.1",
    port: int = 8000,
) -> tuple[DevCommand, DevCommand]:
    """Pure: the ``(backend, frontend)`` commands ``terp dev`` runs.

    Backend = ``uvicorn <app_ref> --reload`` from the project root; frontend = ``npm run dev``
    from ``<root>/<frontend_dir>`` (the copier template + example layout). The frontend command
    is returned unconditionally; the executor runs it only when its directory exists.
    """
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
        ),
        cwd=root_path,
    )
    frontend = DevCommand(
        label="frontend",
        argv=("npm", "run", "dev"),
        cwd=root_path / frontend_dir,
    )
    return backend, frontend


Spawn = Callable[[DevCommand], "subprocess.Popen[bytes]"]
Supervise = Callable[[Sequence["subprocess.Popen[bytes]"]], None]


def _spawn(command: DevCommand) -> subprocess.Popen[bytes]:
    """Start one dev process, resolving its executable on PATH (so ``npm`` works on Windows)."""
    executable = shutil.which(command.argv[0]) or command.argv[0]
    # The argv is an internally composed dev command (uvicorn / npm from dev_plan), run with
    # shell=False, so there is no shell interpolation of untrusted input.
    return subprocess.Popen(  # noqa: S603 - internal dev argv, shell=False (no injection)
        (executable, *command.argv[1:]), cwd=command.cwd
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
    port: int = 8000,
    openapi_out: str = "openapi.json",
    preflight: bool = True,
    export: Callable[..., pathlib.Path] = export_openapi,
    spawn: Spawn = _spawn,
    supervise: Supervise = _supervise,
) -> str:
    """Run the backend + frontend dev servers together, after an OpenAPI preflight.

    The preflight writes the live app's OpenAPI document (the frontend contract's codegen source)
    so the typed client is current before the servers start; pass ``preflight=False`` to skip it.
    uvicorn (``--reload``) and the frontend dev server then run side by side until one exits or is
    interrupted, when the other is stopped too. A repo without ``<frontend_dir>/`` runs backend-only.

    *export* / *spawn* / *supervise* are injected so the orchestration is testable without launching
    real servers. Returns a one-line summary of what was stopped.
    """
    root_path = pathlib.Path(root).resolve()
    backend, frontend = dev_plan(
        app_ref=app_ref, root=root_path, frontend_dir=frontend_dir, host=host, port=port
    )
    if preflight:
        destination = export(app_ref, out=root_path / openapi_out, app_root=root_path)
        print(f"terp dev — OpenAPI preflight wrote {destination}")

    commands = [backend]
    if frontend.cwd.is_dir():
        commands.append(frontend)
    for command in commands:
        print(f"  {command.label:8} → {' '.join(command.argv)}  (cwd {command.cwd})")

    processes = [spawn(command) for command in commands]
    supervise(processes)
    ran = " + ".join(command.label for command in commands)
    return f"terp dev stopped ({ran})"


__all__ = ["DevCommand", "dev_plan", "run_dev_command"]
