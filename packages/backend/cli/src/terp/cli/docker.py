"""``terp docker dev`` — the full-stack workbench: Postgres + backend + frontend via Compose.

Wraps ``docker compose -f <file> watch`` (Compose v2.22+): it brings up the database, runs the
one-shot migrate + seed, starts the API (uvicorn) and the frontend (Vite), and live-syncs source
into the running containers. One command from a checkout to a seeded, running app.

When a one-shot fails, this command also says **why**. Compose reports a failed dependency as

    service "publish-operations" didn't complete successfully: exit 1

— twice, because two waiters observe the same failed condition — and that is the whole
user-visible symptom: a name and a number, with the actual cause (``Connection refused``,
a bad migration, a missing variable) sitting in a container log nobody was told to read.
This command owns the topology, so it knows which services exited non-zero and can print
their last lines before it returns. Reporting an exit code for a failure whose cause you
are holding is the platform knowing the answer and not saying it.

A pure planner (:func:`docker_dev_argv`, :func:`compose_ps_argv`, :func:`compose_logs_argv`)
plus pure parsing (:func:`failed_services`) and a thin executor with the process runners
injected, so the orchestration is testable without Docker.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
from collections.abc import Callable, Sequence

_DEFAULT_COMPOSE = "docker-compose.yml"

#: Lines of a failed service's log to show. Enough for a traceback and the line above it;
#: bounded, because this prints after a failure the reader is already parsing.
_LOG_TAIL_LINES = 50

#: Runs argv, returning its exit status (output goes to the terminal).
Runner = Callable[[Sequence[str]], int]
#: Runs argv, returning ``(exit status, combined output)`` — the diagnostic seam.
Capture = Callable[[Sequence[str]], tuple[int, str]]


def _compose_argv(
    compose_file: str | pathlib.Path, *, project_name: str | None = None
) -> list[str]:
    """The ``docker compose`` prefix every subcommand below shares."""
    argv = ["docker", "compose", "-f", str(compose_file)]
    if project_name:
        argv += ["-p", project_name]
    return argv


def docker_dev_argv(
    compose_file: str | pathlib.Path, *, project_name: str | None = None
) -> tuple[str, ...]:
    """The ``docker compose`` argv that runs the workbench with file-watching."""
    return (*_compose_argv(compose_file, project_name=project_name), "watch")


def compose_ps_argv(
    compose_file: str | pathlib.Path, *, project_name: str | None = None
) -> tuple[str, ...]:
    """The argv listing every container of the project, running or not, as JSON."""
    return (
        *_compose_argv(compose_file, project_name=project_name),
        "ps",
        "--all",
        "--format",
        "json",
    )


def compose_logs_argv(
    compose_file: str | pathlib.Path,
    service: str,
    *,
    tail: int = _LOG_TAIL_LINES,
    project_name: str | None = None,
) -> tuple[str, ...]:
    """The argv printing *service*'s last *tail* log lines."""
    return (
        *_compose_argv(compose_file, project_name=project_name),
        "logs",
        "--no-color",
        f"--tail={tail}",
        service,
    )


def failed_services(ps_output: str) -> tuple[str, ...]:
    """Service names that exited non-zero, from ``compose ps --format json`` output.

    Compose has emitted both a JSON array and newline-delimited objects across versions,
    so both are accepted. Deduplicated and ordered: compose reports one failed one-shot
    once per waiter that observed it, and repeating a service's log per waiter would
    reproduce the noise this exists to replace.
    """
    entries: list[dict] = []
    stripped = ps_output.strip()
    if not stripped:
        return ()
    try:
        parsed = json.loads(stripped)
        entries = parsed if isinstance(parsed, list) else [parsed]
    except json.JSONDecodeError:
        for line in stripped.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict):
                entries.append(entry)
    names: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        exit_code = entry.get("ExitCode")
        service = entry.get("Service") or entry.get("Name")
        if isinstance(exit_code, int) and exit_code != 0 and isinstance(service, str):
            if service not in names:
                names.append(service)
    return tuple(names)


def _run(argv: Sequence[str]) -> int:
    """Run *argv*, resolving the executable on PATH (so ``docker`` works on Windows)."""
    executable = shutil.which(argv[0]) or argv[0]
    return subprocess.call([executable, *argv[1:]])  # noqa: S603 - fixed argv, shell=False


def _capture(argv: Sequence[str]) -> tuple[int, str]:
    """Run *argv* capturing its combined output (the diagnostic calls)."""
    executable = shutil.which(argv[0]) or argv[0]
    completed = subprocess.run(  # noqa: S603 - fixed argv, shell=False
        [executable, *argv[1:]],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return completed.returncode, f"{completed.stdout}{completed.stderr}"


def diagnose_failure(
    compose_path: pathlib.Path,
    *,
    project_name: str | None = None,
    capture: Capture,
) -> str:
    """The last lines of every service that exited non-zero, as a report.

    Best-effort by construction: this runs *after* a failure the caller is already
    reporting, so a daemon that has gone away, a torn-down project, or an unparsable
    ``ps`` must not replace the real error with an error about diagnosing it.
    """
    status, ps_output = capture(
        compose_ps_argv(compose_path, project_name=project_name)
    )
    if status != 0:
        return ""
    services = failed_services(ps_output)
    if not services:
        return ""
    sections: list[str] = []
    for service in services:
        _, logs = capture(
            compose_logs_argv(compose_path, service, project_name=project_name)
        )
        body = logs.strip() or "(no output captured)"
        sections.append(
            f"--- last {_LOG_TAIL_LINES} lines of {service!r} "
            f"(the service that failed) ---\n{body}"
        )
    listing = ", ".join(repr(service) for service in services)
    return (
        f"\nterp docker dev: {len(services)} service(s) exited non-zero: {listing}\n"
        "Compose reports only the exit code, so here is what they actually said:\n\n"
        + "\n\n".join(sections)
        + f"\n\nFull logs: docker compose -f {compose_path.name} logs <service>"
    )


def run_docker_dev_command(
    *,
    compose_file: str = _DEFAULT_COMPOSE,
    root: str | pathlib.Path = ".",
    project_name: str | None = None,
    runner: Runner | None = None,
    capture: Capture | None = None,
) -> str:
    """Resolve the compose file under *root* and run ``docker compose watch``.

    A missing compose file fails closed with a clean CLI error. On a non-zero exit the
    failing services' logs are appended to the returned message, so the cause travels
    with the verdict. *runner* / *capture* are injected in tests so the orchestration is
    verified without Docker.
    """
    candidate = pathlib.Path(compose_file)
    path = (
        candidate
        if candidate.is_absolute()
        else pathlib.Path(root).resolve() / candidate
    )
    if not path.is_file():
        raise SystemExit(
            f"compose file not found: {path} (looked under --root {root!r})"
        )
    status = (runner or _run)(docker_dev_argv(path, project_name=project_name))
    message = f"docker compose watch exited with status {status}"
    if status == 0:
        return message
    diagnosis = diagnose_failure(
        path, project_name=project_name, capture=capture or _capture
    )
    return f"{message}\n{diagnosis}" if diagnosis else message
