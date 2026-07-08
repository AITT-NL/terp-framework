"""``terp docker dev`` — the full-stack workbench: Postgres + backend + frontend via Compose watch.

Wraps ``docker compose -f <file> watch`` (Compose v2.22+): it brings up the database, runs the
one-shot migrate + seed, starts the API (uvicorn) and the frontend (Vite), and live-syncs source
into the running containers. One command from a checkout to a seeded, running app.

A pure planner (:func:`docker_dev_argv`) plus a thin executor (:func:`run_docker_dev_command`)
with the process runner injected, so the orchestration is testable without Docker.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess
from collections.abc import Callable, Sequence

_DEFAULT_COMPOSE = "docker-compose.yml"

Runner = Callable[[Sequence[str]], int]


def docker_dev_argv(
    compose_file: str | pathlib.Path, *, project_name: str | None = None
) -> tuple[str, ...]:
    """The ``docker compose`` argv that runs the workbench with file-watching."""
    argv = ["docker", "compose", "-f", str(compose_file)]
    if project_name:
        argv += ["-p", project_name]
    argv.append("watch")
    return tuple(argv)


def _run(argv: Sequence[str]) -> int:
    """Run *argv*, resolving the executable on PATH (so ``docker`` works on Windows)."""
    executable = shutil.which(argv[0]) or argv[0]
    return subprocess.call([executable, *argv[1:]])  # noqa: S603 - fixed argv, shell=False


def run_docker_dev_command(
    *,
    compose_file: str = _DEFAULT_COMPOSE,
    root: str | pathlib.Path = ".",
    project_name: str | None = None,
    runner: Runner | None = None,
) -> str:
    """Resolve the compose file under *root* and run ``docker compose watch``.

    A missing compose file fails closed with a clean CLI error. *runner* is injected in tests so
    the orchestration is verified without Docker; it returns the exit status of the watch process.
    """
    candidate = pathlib.Path(compose_file)
    path = candidate if candidate.is_absolute() else pathlib.Path(root).resolve() / candidate
    if not path.is_file():
        raise SystemExit(f"compose file not found: {path} (looked under --root {root!r})")
    status = (runner or _run)(docker_dev_argv(path, project_name=project_name))
    return f"docker compose watch exited with status {status}"
