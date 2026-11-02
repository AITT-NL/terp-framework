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

It also keeps ``watch`` on the configuration the containers run. ``watch`` loads the
project once, when it starts, and every rebuild after that converges the WHOLE project
against that copy: a service whose configuration differs from it is recreated from the
copy, and only the rebuilt service and its dependents are started again. Two things made
them differ, both measured on Compose v2.40.3 with the reference app:

- a settings change. ``watch`` never sees it, so after ``.app.env`` changed and
  ``docker compose up -d`` applied it, a frontend dependency change put every backend
  service back on the OLD settings and left all of them stopped, with no error;
- ``up`` itself. v2's ``watch`` keeps a service's ``env_file`` list in the project it
  hashes and ``up`` drops it after reading the files, so the two disagree about every
  service with an ``env_file`` even when nothing changed: an ``up -d`` beside a running
  ``watch``, or a ``watch --no-up`` after an ``up``, and the next frontend rebuild stopped
  the whole backend.

So this command watches the files the project is loaded from (:func:`model_inputs`), and
when one changes it stops ``watch`` and starts it again: its own ``up`` applies the change
(recreating what it touched) with the same hashes its rebuilds will use. A settings change
needs no command of its own, and there is never an ``up`` beside the ``watch``.

A pure planner (:func:`docker_dev_argv`, :func:`compose_ps_argv`, :func:`compose_logs_argv`)
plus pure parsing (:func:`failed_services`) and a thin executor with the process runners
injected, so the orchestration is testable without Docker.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from typing import Protocol

from terp.cli import ports
from terp.cli._output import emit
from terp.cli.docker_masks import clear_stale_masks

_DEFAULT_COMPOSE = "docker-compose.yml"

#: Lines of a failed service's log to show. Enough for a traceback and the line above it;
#: bounded, because this prints after a failure the reader is already parsing.
_LOG_TAIL_LINES = 50

#: Seconds between two looks at the files the compose project is loaded from. Hashing a
#: handful of small files costs nothing, and a settings change is applied within a second.
_POLL_SECONDS = 1.0

#: Seconds a stopped ``watch`` gets to exit before it is killed. It holds no state of its
#: own (the containers keep running without it), so there is nothing to wait out.
_STOP_SECONDS = 10

#: The signal that ends a process group outright, where the platform has one. Only the
#: POSIX branch of :func:`_stop` sends it; Windows ends the tree with ``taskkill /F``.
_KILL = getattr(signal, "SIGKILL", signal.SIGTERM)

#: Runs argv, returning its exit status (output goes to the terminal).
Runner = Callable[[Sequence[str]], int]
#: Runs argv, returning ``(exit status, combined output)`` — the diagnostic seam.
Capture = Callable[[Sequence[str]], tuple[int, str]]


class Process(Protocol):
    """The part of a running ``watch`` this module drives (a :class:`subprocess.Popen`)."""

    pid: int

    def poll(self) -> int | None: ...

    def wait(self, timeout: float | None = None) -> int: ...

    def kill(self) -> None: ...


#: Starts argv without waiting for it.
Spawn = Callable[[Sequence[str]], Process]
#: Stops a running process and everything it started, and waits until it has.
Stop = Callable[[Process], None]


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


def _declared_env_files(compose_path: pathlib.Path) -> tuple[str, ...]:
    """Every ``env_file`` a service of *compose_path* names, as written (short or long form).

    Read as data with PyYAML, so the anchor every backend service merges is resolved. A
    file that cannot be read declares nothing here: ``watch`` is about to say why in its
    own words, and an interpolated path (``${X}/.app.env``) names nothing this command
    could watch without resolving it the way compose does.
    """
    import yaml  # Lazily: only this command reads a compose file this way.

    try:
        data = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return ()
    services = data.get("services") if isinstance(data, dict) else None
    found: list[str] = []
    for service in services.values() if isinstance(services, dict) else ():
        declared = service.get("env_file") if isinstance(service, dict) else None
        for entry in declared if isinstance(declared, list) else [declared]:
            path = entry.get("path") if isinstance(entry, dict) else entry
            if isinstance(path, str) and "$" not in path and path not in found:
                found.append(path)
    return tuple(found)


def model_inputs(compose_path: pathlib.Path) -> tuple[pathlib.Path, ...]:
    """The files compose builds this project from: what a running ``watch`` has a copy of.

    The compose file, the ``.env`` beside it that its ``${...}`` interpolations read, and
    every ``env_file`` its services forward (``.app.env``, and a scoped app's
    ``.app.<service>.env``). A change to any of them changes a container's configuration,
    and a ``watch`` started before it would recreate that container from the old copy.
    """
    directory = compose_path.parent
    found = {compose_path, directory / ".env"}
    found.update(directory / name for name in _declared_env_files(compose_path))
    return tuple(sorted(found))


def _fingerprint(paths: Sequence[pathlib.Path]) -> dict[pathlib.Path, str | None]:
    """Each path's content digest, ``None`` for one that does not exist (yet).

    By content, not by modification time: an editor that saves an unchanged file, or a
    ``terp env set`` that writes the value already there, changes nothing a container
    sees, and restarting ``watch`` for it would be a recreate nobody asked for.
    """
    digests: dict[pathlib.Path, str | None] = {}
    for path in paths:
        try:
            digests[path] = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            digests[path] = None
    return digests


def _spawn(
    argv: Sequence[str],
    *,
    platform: str = sys.platform,
    popen: Callable[..., Process] = subprocess.Popen,
) -> Process:
    """Start *argv* (resolving the executable on PATH) without waiting for it.

    Outside Windows the child gets a process group of its own, because ``docker compose``
    is two processes: the ``docker`` CLI and the compose plugin it starts. With a terminal
    attached, the CLI does not pass a signal on to the plugin -- it leaves that to the
    terminal, which signals the whole foreground group -- so a signal sent to the CLI
    alone would leave the plugin watching. Signalling the group (:func:`_stop`) reaches
    both. Ctrl+C now reaches this process only, and stopping the group on the way out is
    how it reaches ``watch``. On Windows ``taskkill /T`` ends the tree instead, and the
    console's Ctrl+C still reaches every process attached to it.
    """
    executable = shutil.which(argv[0]) or argv[0]
    options: dict[str, object] = {} if platform == "win32" else {"process_group": 0}
    return popen([executable, *argv[1:]], **options)


def _stop(
    process: Process,
    *,
    platform: str = sys.platform,
    run: Callable[..., object] = subprocess.run,
    signal_group: Callable[[int, int], None] | None = None,
    wait_seconds: float = _STOP_SECONDS,
) -> None:
    """Stop a ``watch`` and the compose plugin beneath it, and wait until both have.

    Windows: ``taskkill /T /F``, the tree, as ``terp dev`` stops its servers. Elsewhere:
    SIGINT to the process group :func:`_spawn` gave it, which ``watch`` treats as Ctrl+C.
    Neither stops a container: ``watch`` leaves the stack running when it exits, and the
    restart converges it.
    """
    if process.poll() is not None:
        return
    windows = platform == "win32"
    if windows:
        system_root = pathlib.Path(os.environ.get("SystemRoot", "C:\\Windows"))
        taskkill = system_root / "System32" / "taskkill.exe"
        run([str(taskkill), "/PID", str(process.pid), "/T", "/F"], capture_output=True, check=False)
    else:
        group = signal_group or os.killpg  # POSIX only; Windows took the branch above
        group(process.pid, signal.SIGINT)
    try:
        process.wait(timeout=wait_seconds)
    except subprocess.TimeoutExpired:
        if windows:
            process.kill()
        else:
            group(process.pid, _KILL)
        process.wait()


class _Finished:
    """A process that has already run to completion: what an injected *runner* produces.

    Lets a caller (and every test written before ``watch`` was supervised) keep injecting
    a blocking runner: the session sees a ``watch`` that has exited with its status.
    """

    pid = 0

    def __init__(self, status: int) -> None:
        self._status = status

    def poll(self) -> int:
        return self._status

    def wait(self, timeout: float | None = None) -> int:
        return self._status

    def kill(self) -> None:
        return None


def _watch_session(
    compose_path: pathlib.Path,
    *,
    project_name: str | None,
    spawn: Spawn,
    stop: Stop,
    inputs: Callable[[pathlib.Path], Sequence[pathlib.Path]] = model_inputs,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Run ``watch`` until it exits, starting it again whenever its configuration changes.

    Again means the whole ``watch``, its own ``up`` included -- never an ``up -d`` and a
    ``watch --no-up``, which leave Compose v2's two hashes of every ``env_file`` service
    disagreeing (see the module docstring). What that costs is the image check the first
    start makes too: both images are built from the layer cache, which is quick unless the
    build context changed since the last build.

    Returns ``watch``'s own exit status. On Ctrl+C the running ``watch`` is stopped and the
    interrupt goes on, as it did before this command supervised anything.
    """
    argv = docker_dev_argv(compose_path, project_name=project_name)
    paths = inputs(compose_path)
    seen = _fingerprint(paths)
    process = spawn(argv)
    try:
        while (status := process.poll()) is None:
            sleep(_POLL_SECONDS)
            current = _fingerprint(paths)
            if current == seen:
                continue
            changed = ", ".join(path.name for path in paths if current[path] != seen[path])
            emit(
                f"terp docker dev: {changed} changed -- starting docker compose watch again, "
                "so the stack and every rebuild after this run on the new configuration"
            )
            stop(process)
            paths = inputs(compose_path)
            seen = _fingerprint(paths)
            process = spawn(argv)
        return status
    finally:
        stop(process)


def run_docker_dev_command(
    *,
    compose_file: str = _DEFAULT_COMPOSE,
    root: str | pathlib.Path = ".",
    project_name: str | None = None,
    runner: Runner | None = None,
    capture: Capture | None = None,
    spawn: Spawn | None = None,
    stop: Stop = _stop,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    """Resolve the compose file under *root* and run ``docker compose watch``.

    A missing compose file fails closed with a clean CLI error. On a non-zero exit the
    failing services' logs are appended to the returned message, so the cause travels
    with the verdict. While it runs, a change to a file the project is loaded from is
    applied and ``watch`` started again on it (:func:`_watch_session`).

    *runner* / *capture* / *spawn* / *stop* / *sleep* are injected in tests so the
    orchestration is verified without Docker. A *runner* alone also runs ``watch``, to
    completion, the way this command ran it before it supervised anything.
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
    # Before the stack, not after it: the compose file requires its host ports to
    # be assigned, and this is what makes that requirement invisible to somebody
    # who has never heard of `terp ports`. One command from a checkout to a
    # running app, which is the promise this command already makes and the
    # property ADR 0134 decision 1 refuses to spend in order to enforce decision
    # 3. Never fatal — `ensure_assigned` reports instead of raising, because a
    # start that dies over a ledger is worse than one that lets compose speak.
    #
    # Assigned beside the COMPOSE FILE, not beside --root. Compose's project
    # directory defaults to the directory of the first `-f`, and that is the only
    # `.env` it reads — so publishing into --root would write the assignment into
    # a file this very command then ignores, and the start would fail on a
    # required variable that had just been "set". The two coincide in the ordinary
    # case and part company for an absolute or nested --compose-file, which is
    # exactly where the mistake would have been silent.
    _, note = ports.ensure_assigned(path.parent)
    if note:
        print(note)
    # Before `watch` creates anything: a workbench from before 0.30.0 holds its
    # node_modules mask as a volume, which Compose would reattach over the tmpfs the
    # compose file now declares and keep serving old packages from
    # (terp.cli.docker_masks). No docker on PATH is `watch`'s to report, in its own
    # words, not this check's.
    try:
        cleared = clear_stale_masks(path, project_name=project_name, capture=capture or _capture)
    except OSError:
        cleared = ""
    if cleared:
        # Through the CLI's one output seam, and flushed: `watch` holds the terminal next.
        emit(cleared)
    if spawn is None:
        spawn = _spawn if runner is None else (lambda argv: _Finished(runner(argv)))
    status = _watch_session(
        path, project_name=project_name, spawn=spawn, stop=stop, sleep=sleep
    )
    message = f"docker compose watch exited with status {status}"
    if status == 0:
        return message
    diagnosis = diagnose_failure(
        path, project_name=project_name, capture=capture or _capture
    )
    return f"{message}\n{diagnosis}" if diagnosis else message
