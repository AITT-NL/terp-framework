"""``terp smoke`` — run the workbench's boot chain in-process, with no Docker daemon.

Answers one question: **is this my app, or is this my environment?**

When the workbench fails, the two candidates are an app defect and a broken environment
seam, and separating them used to mean hand-assembling the chain the compose file already
declares -- migrate, seed, the API, each one-shot publisher -- against SQLite, by reading
the topology out of ``docker-compose.yml`` and translating every container path and
container address by hand. That is a mechanical derivation of a file the platform ships,
so the platform can do it: the topology is declared, the commands are declared, and the
dependency order is declared.

What it runs is the backend chain, not the whole workbench: the services sharing the API's
image (migrate, seed, the API, any one-shot the app added), ordered by ``depends_on``.
Postgres is replaced by a throwaway SQLite file and the frontend dev server is irrelevant
to whether the backend boots, so neither is started -- which is what makes this need no
daemon and run in CI.

Three translations make a container command runnable on the host, and all are read from the
compose file rather than guessed:

* **paths** -- a bind mount (``./app:/app/app``) says what ``/app/app`` means here;
* **addresses** -- ``http://api:8000`` is a compose-network name that does not resolve on
  the host, so a value naming a service is rewritten to ``127.0.0.1`` and the port the
  API was actually started on. (This is the same host/container distinction the manifest
  records as ``resolvedBy``; see ``terp guide environment``.)
* **what the substituted database cannot do** -- per-module schemas are PostgreSQL-only
  (ADR 0070), so against the throwaway SQLite the declared layout is moved to ``flat``.
  Without it the platform refused its own combination and nothing booted, which made this
  command unavailable to precisely the apps most likely to be asking. Pass
  ``--database-url`` pointing at a real PostgreSQL to keep the app's own layout.

Every translation is ANNOUNCED (``SmokePlan.translations``), because a run whose
configuration was moved is not evidence about the configuration the app ships.

A pure planner (:func:`smoke_plan`) plus a thin executor with the process runner injected,
so the plan is verified without running anything.
"""

from __future__ import annotations

import contextlib
import os
import pathlib
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

#: How long to wait for the API to answer its health probe before giving up.
_HEALTH_TIMEOUT_SECONDS = 60.0
_HEALTH_POLL_SECONDS = 0.5

#: The liveness path the template's healthcheck uses.
_HEALTH_PATH = "/health/live"

#: Runs argv with an environment and working directory; returns (status, output).
Runner = Callable[[Sequence[str], Mapping[str, str], pathlib.Path], tuple[int, str]]


@dataclass(frozen=True)
class SmokeStep:
    """One service of the chain, translated to something runnable on this host."""

    service: str
    argv: tuple[str, ...]
    environment: dict[str, str]
    #: ``one-shot`` runs to completion; ``server`` runs in the background and is
    #: health-probed, because the one-shots after it dial it.
    kind: str


@dataclass(frozen=True)
class SmokePlan:
    """The whole chain, plus what the executor needs to run and tear it down."""

    steps: tuple[SmokeStep, ...]
    database_url: str
    api_port: int
    skipped: tuple[str, ...] = field(default=())
    #: Settings this command had to CHANGE to make the chain runnable on the host,
    #: announced rather than silent: a translated run is not exercising the app's own
    #: configuration, and a reader comparing a green smoke against a red deployment
    #: needs to know which knob moved.
    translations: tuple[str, ...] = field(default=())


def _load_compose(path: pathlib.Path) -> dict:
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _depends_on(service: object) -> dict[str, str | None]:
    """A service's ``depends_on`` as name -> condition (list form has no condition)."""
    if not isinstance(service, dict):
        return {}
    declared = service.get("depends_on")
    if isinstance(declared, list):
        return {str(name): None for name in declared}
    if isinstance(declared, dict):
        return {
            str(name): (spec or {}).get("condition") if isinstance(spec, dict) else None
            for name, spec in declared.items()
        }
    return {}


def _backend_services(services: Mapping[str, dict]) -> list[str]:
    """Every service running the same image as ``api`` — the backend chain.

    Image identity rather than a name list: the template's one-shots exist to run the
    backend's own entrypoints and share its tag through a YAML anchor, and an app that
    adds a publisher adds it to that same anchor. Naming migrate/seed/api explicitly
    would silently skip exactly the app-added one-shots this command exists to exercise.
    """
    api = services.get("api")
    image = api.get("image") if isinstance(api, dict) else None
    if not image:
        return ["api"] if isinstance(api, dict) else []
    return [
        name
        for name, service in services.items()
        if isinstance(service, dict) and service.get("image") == image
    ]


def _ordered(services: Mapping[str, dict], selected: Sequence[str]) -> list[str]:
    """*selected* in ``depends_on`` order (stable; dependencies outside it ignored)."""
    remaining = list(selected)
    chosen: list[str] = []
    while remaining:
        ready = [
            name
            for name in remaining
            if all(
                dependency in chosen or dependency not in selected
                for dependency in _depends_on(services[name])
            )
        ]
        if not ready:
            # A cycle, or a dependency we cannot satisfy: keep the declared order rather
            # than refuse — this command diagnoses, it does not gate.
            chosen.extend(remaining)
            break
        chosen.extend(ready)
        remaining = [name for name in remaining if name not in ready]
    return chosen


def _mounts(service: Mapping, environment: Mapping[str, str]) -> list[tuple[str, str]]:
    """``(host, container)`` pairs from a service's short-form bind mounts.

    Interpolated BEFORE splitting: the template's mounts are written
    ``${TERP_DEV_HOST_ROOT:-.}/app:/app/app``, and that default value contains the very
    colon the split is looking for — so resolving first is what keeps the host half from
    being torn in two.
    """
    pairs: list[tuple[str, str]] = []
    for volume in service.get("volumes") or []:
        if not isinstance(volume, str):
            continue
        parts = _interpolate(volume, environment).split(":")
        # A Windows host path carries its own drive colon (`C:\src\app:/app/app`), so the
        # container half is the LAST absolute-looking part, not simply parts[1].
        if len(parts) < 2 or not parts[-1].startswith("/"):
            continue
        pairs.append((":".join(parts[:-1]), parts[-1]))
    return pairs


def _host_path(
    service: Mapping,
    container_path: str,
    root: pathlib.Path,
    environment: Mapping[str, str],
) -> str:
    """Translate a container path through the service's bind mounts."""
    for host, container in _mounts(service, environment):
        if container_path == container or container_path.startswith(f"{container}/"):
            local = pathlib.PurePath(host)
            suffix = container_path[len(container) :].strip("/")
            base = local if local.is_absolute() else root / host
            return str(base / suffix if suffix else base)
    return container_path


def _interpolate(value: str, environment: Mapping[str, str]) -> str:
    """Resolve ``${VAR}`` / ``${VAR:-default}`` the way compose would, from *environment*."""
    out, index = [], 0
    while index < len(value):
        start = value.find("${", index)
        if start == -1:
            out.append(value[index:])
            break
        out.append(value[index:start])
        end = value.find("}", start)
        if end == -1:
            out.append(value[start:])
            break
        body = value[start + 2 : end]
        name, _, default = body.partition(":-")
        name = name.split(":?")[0].split("?")[0]
        out.append(environment.get(name) or default)
        index = end + 1
    return "".join(out)


def _rewrite_addresses(value: str, service_names: Sequence[str], api_port: int) -> str:
    """Point a compose-network address at the host copy of the same service.

    ``http://api:8000`` names a DNS entry that exists only on the compose network. The
    API is the only service this chain actually starts, so a value naming it becomes
    ``127.0.0.1:<the port we bound>``; that is the whole reason a host run of a
    container command otherwise dies with ``Connection refused``.
    """
    rewritten = value
    for name in service_names:
        for prefix in (f"//{name}:", f"@{name}:"):
            if prefix not in rewritten:
                continue
            head, _, tail = rewritten.partition(prefix)
            # `8000/path` -> drop the container port, keep the path.
            _, slash, path = tail.partition("/")
            local = prefix.replace(name, "127.0.0.1")
            rewritten = f"{head}{local}{api_port}{slash}{path}"
    return rewritten


def _free_port() -> int:
    with contextlib.closing(socket.socket()) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _read_env_file(path: pathlib.Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return values
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        name, separator, value = stripped.partition("=")
        if separator:
            values[name.strip()] = value.strip().strip("'\"")
    return values


def _service_environment(service: Mapping) -> dict[str, str]:
    declared = service.get("environment")
    if isinstance(declared, dict):
        return {str(k): "" if v is None else str(v) for k, v in declared.items()}
    if isinstance(declared, list):
        entries: dict[str, str] = {}
        for item in declared:
            name, _, value = str(item).partition("=")
            entries[name] = value
        return entries
    return {}


def smoke_plan(
    root: str | pathlib.Path = ".",
    *,
    compose_file: str = "docker-compose.yml",
    database_url: str | None = None,
    api_port: int | None = None,
) -> SmokePlan:
    """Translate the compose topology into a runnable host chain (pure; runs nothing)."""
    project_root = pathlib.Path(root).resolve()
    compose_path = project_root / compose_file
    if not compose_path.is_file():
        raise SystemExit(
            f"compose file not found: {compose_path} (looked under --root {root!r})"
        )
    compose = _load_compose(compose_path)
    services = {
        name: service
        for name, service in (compose.get("services") or {}).items()
        if isinstance(service, dict)
    }
    if not services:
        raise SystemExit(f"{compose_file} declares no services")
    backend = _ordered(services, _backend_services(services))
    if not backend:
        raise SystemExit(
            f"{compose_file} declares no service sharing the api image - nothing to smoke"
        )
    port = api_port or _free_port()
    url = database_url or "sqlite:///./.terp-smoke.db"

    # `.app.env` first, then compose's `environment:` — the same precedence compose
    # applies, so what this runs is what the workbench would run.
    app_env = _read_env_file(project_root / ".app.env")
    dot_env = {**_read_env_file(project_root / ".env"), **os.environ}
    all_service_names = list(services)

    steps: list[SmokeStep] = []
    translations: set[str] = set()
    for name in backend:
        service = services[name]
        command = service.get("command")
        if not isinstance(command, list) or not command:
            continue
        environment = dict(app_env)
        for key, raw in _service_environment(service).items():
            environment[key] = _interpolate(str(raw), dot_env)
        environment = {
            key: _rewrite_addresses(value, all_service_names, port)
            for key, value in environment.items()
        }
        # The database and the bind-mounted checkout are this run's, not the compose
        # network's; set them last so nothing above can put Postgres back.
        environment["DATABASE_URL"] = url
        environment.setdefault("ENVIRONMENT", "local")
        # Per-module schemas are PostgreSQL-only (ADR 0070) and the substituted database
        # is SQLite by default, so the platform refused its own combination and the app
        # could not boot at all — which made this command unavailable to exactly the apps
        # most likely to be asking "is it my app or my environment?". Translated the way
        # container addresses and bind-mounted paths already are, and only when the
        # substituted database cannot honour the declared layout: pass `--database-url`
        # pointing at a real PostgreSQL and the app's own layout is preserved.
        if environment.get("DB_SCHEMA_LAYOUT") == "per-module" and not url.startswith(
            "postgresql"
        ):
            environment["DB_SCHEMA_LAYOUT"] = "flat"
            translations.add(
                "DB_SCHEMA_LAYOUT per-module -> flat (per-module needs PostgreSQL, "
                "ADR 0070; pass --database-url to keep it)"
            )
        # The image sets WORKDIR=/app and installs the app editable, so `app` and
        # `control_plane` import by name. On the host that holds only after `uv sync`,
        # which is precisely what a checkout being diagnosed may not have done — so put
        # the project root on the path rather than fail with an ImportError that is an
        # artifact of this translation instead of a fact about the app.
        existing = os.environ.get("PYTHONPATH", "")
        environment["PYTHONPATH"] = (
            f"{project_root}{os.pathsep}{existing}" if existing else str(project_root)
        )
        argv = tuple(
            _host_path(service, str(part), project_root, dot_env)
            if str(part).startswith("/")
            else str(part)
            for part in command
        )
        is_server = "healthcheck" in service
        if is_server:
            # Bind the port we probe, on loopback, and never --reload: a reloader forks a
            # child the executor cannot wait on or terminate cleanly.
            argv = _strip_flags(argv, {"--host", "--port"}, {"--reload"})
            argv += ("--host", "127.0.0.1", "--port", str(port))
        steps.append(
            SmokeStep(
                service=name,
                argv=argv,
                environment=environment,
                kind="server" if is_server else "one-shot",
            )
        )
    skipped = tuple(name for name in services if name not in backend)
    return SmokePlan(
        steps=tuple(steps),
        database_url=url,
        api_port=port,
        skipped=skipped,
        translations=tuple(sorted(translations)),
    )


def _strip_flags(
    argv: tuple[str, ...], with_value: set[str], standalone: set[str]
) -> tuple[str, ...]:
    """Drop *standalone* flags and each *with_value* flag together with its argument."""
    out: list[str] = []
    skip_next = False
    for part in argv:
        if skip_next:
            skip_next = False
            continue
        if part in with_value:
            skip_next = True
            continue
        if part in standalone:
            continue
        out.append(part)
    return tuple(out)


def render_smoke_plan(
    *, root: str | pathlib.Path = ".", compose_file: str = "docker-compose.yml"
) -> str:
    """The chain as text, without running it (``terp smoke --plan``).

    The point of a dry run here is that the translation is the interesting part: it shows
    which container path and which container address each step resolved to, so a wrong
    answer is visible before anything executes.
    """
    plan = smoke_plan(root, compose_file=compose_file)
    lines = [
        f"terp smoke plan - {len(plan.steps)} backend service(s)",
        f"  database: {plan.database_url}",
        f"  api port: {plan.api_port} (host loopback)",
        f"  skipped:  {', '.join(plan.skipped) or 'nothing'} (not the backend image)",
        "",
    ]
    for step in plan.steps:
        lines.append(f"  [{step.kind}] {step.service}")
        lines.append(f"      {' '.join(step.argv)}")
        for key in sorted(step.environment):
            lines.append(f"      {key}={step.environment[key]}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _default_runner(
    argv: Sequence[str], environment: Mapping[str, str], cwd: pathlib.Path
) -> tuple[int, str]:
    executable = shutil.which(argv[0]) or argv[0]
    completed = subprocess.run(  # noqa: S603 - argv comes from the app's own compose file
        [executable, *argv[1:]],
        cwd=cwd,
        env={**os.environ, **environment},
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return completed.returncode, f"{completed.stdout}{completed.stderr}"


def _await_health(port: int, timeout: float = _HEALTH_TIMEOUT_SECONDS) -> bool:
    deadline = time.monotonic() + timeout
    url = f"http://127.0.0.1:{port}{_HEALTH_PATH}"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:  # noqa: S310
                if 200 <= response.status < 300:
                    return True
        except (urllib.error.URLError, OSError, ValueError):
            pass
        time.sleep(_HEALTH_POLL_SECONDS)
    return False


def run_smoke_command(
    *,
    root: str | pathlib.Path = ".",
    compose_file: str = "docker-compose.yml",
    runner: Runner | None = None,
) -> int:
    """Run the plan; return 0 when the whole chain completes, 1 on the first failure.

    Prints each step as it runs and the failing step's own output — the thing a bare
    ``exit 1`` withholds.
    """
    project_root = pathlib.Path(root).resolve()
    plan = smoke_plan(project_root, compose_file=compose_file)
    execute = runner or _default_runner
    print(
        f"terp smoke: {len(plan.steps)} backend service(s) against {plan.database_url}\n"
        f"terp smoke: skipping {', '.join(plan.skipped) or 'nothing'} "
        "(not the backend image)",
    )
    for note in plan.translations:
        print(f"terp smoke: translated {note}")
    server: subprocess.Popen[bytes] | None = None
    try:
        for step in plan.steps:
            printable = " ".join(step.argv)
            if step.kind == "server":
                print(f"terp smoke: starting {step.service} - {printable}")
                server = _spawn_server(step, project_root)
                if not _await_health(plan.api_port):
                    print(
                        f"terp smoke: FAILED - {step.service} never answered "
                        f"{_HEALTH_PATH} on port {plan.api_port}"
                    )
                    return 1
                print(f"terp smoke: {step.service} is live on port {plan.api_port}")
                continue
            print(f"terp smoke: running {step.service} - {printable}")
            status, output = execute(step.argv, step.environment, project_root)
            if status != 0:
                print(
                    f"terp smoke: FAILED - {step.service} exited {status}\n"
                    f"--- {step.service} output ---\n{output.strip()}"
                )
                return 1
    finally:
        if server is not None and server.poll() is None:
            server.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                server.wait(timeout=10)
    print("terp smoke: the whole boot chain completed - the app boots on this checkout")
    return 0


def _spawn_server(step: SmokeStep, cwd: pathlib.Path) -> subprocess.Popen[bytes]:
    executable = shutil.which(step.argv[0]) or step.argv[0]
    return subprocess.Popen(  # noqa: S603 - argv comes from the app's own compose file
        [executable, *step.argv[1:]],
        cwd=cwd,
        env={**os.environ, **step.environment},
    )
