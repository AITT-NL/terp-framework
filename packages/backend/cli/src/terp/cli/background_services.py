"""Does the production profile run a process for the work the control plane declares?

The profile half of ``terp verify --only production-readiness`` (ADR 0223). Without a process
for it, declared work does not happen while the API starts and reports healthy, and nothing
at boot says so; it is reported apart from the boot refusals, each problem with its own
consequence.

What is required follows the engines installed in the gate's environment, which is the
app's (``uv run terp verify``), so it is what the image installs:

* a declared job needs ``terp jobs worker --forever`` where ``terp-cap-outbox`` is
  installed, a Celery worker where ``terp-cap-jobs-celery`` is, either where both are, and
  nothing where neither is: the default queue then runs a job inline, where it is enqueued;
* a declared schedule needs ``terp jobs scheduler`` or Celery beat, and a profile that runs
  ``terp jobs scheduler`` for one needs ``terp-cap-scheduler-apscheduler`` as well, since
  without it that process stops at start and restarts in a loop.

A service counts only when a plain ``docker compose up`` starts it and keeps it running: not
one under ``profiles``, scaled to 0 (``scale`` or ``deploy.replicas``), nor ``terp jobs
worker`` as an argument list without ``--forever`` under no restart that repeats a clean
exit, which is a single drain. A shell string is read only for the words: one that names
``terp jobs worker`` counts, as older profiles wrapped a single drain in a shell loop, and
what that shell really runs is a residual this check cannot read.

Independent of declared work, ``compose.runtime-role.yml`` must not name a service the
profile does not define: Compose refuses that stack. It is how a generated build meets a
template update whose overlay names a ``worker`` its own profile has not rendered yet.

Only ``docker-compose.prod.yml`` and that overlay are read, as ``deploy-safety`` reads the
one file: not the ``compose.file`` or ``compose.overrides`` a ``deployment.json`` may name,
so a worker added in an override reads as missing. A project with no
``docker-compose.prod.yml`` is deployed some other way, and which process runs its work is
the deploy tool's business (ADR 0184): a note, never a red. A file that does not parse is a
red, as in ``deploy-safety``; one that parses to no services runs none, and is judged so.
"""

from __future__ import annotations

import importlib.util
import pathlib
import re
import shlex
from collections.abc import Callable, Sequence
from typing import Any

from terp.core import ControlPlane

#: The production profile read for the processes, the file ``deploy-safety`` audits.
PROD_PROFILE = "docker-compose.prod.yml"

#: The overlay that gives the profile's services the runtime role (ADR 0223).
RUNTIME_ROLE_OVERLAY = "compose.runtime-role.yml"

#: The module each engine installs, as the gate's environment is asked for it.
OUTBOX = "terp.capabilities.outbox"
CELERY_JOBS = "terp.capabilities.jobs_celery"
CELERY_BEAT = "terp.capabilities.scheduler_celery_beat"
APSCHEDULER = "terp.capabilities.scheduler_apscheduler"

_SHELL_WORDS = {
    "terp-worker": re.compile(r"\bterp\s+jobs\s+worker\b"),
    "terp-scheduler": re.compile(r"\bterp\s+jobs\s+scheduler\b"),
    "celery-worker": re.compile(r"\bcelery\b.*\sworker\b"),
    "celery-beat": re.compile(r"\bcelery\b.*(\sbeat\b|\s-B\b|\s--beat\b)"),
}
_LOOPING_RESTARTS = ("always", "unless-stopped")
_SHOWN = 5
_COMMANDS = {
    "worker": ('["terp", "jobs", "worker", "--forever"]', "worker"),
    "scheduler": ('["terp", "jobs", "scheduler"]', "beat"),
}


def _installed(module: str) -> bool:
    """Whether *module* imports in the gate's environment."""
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def _runs(service: dict[str, Any]) -> set[str]:
    """The processes *service* keeps running under a plain ``docker compose up``."""
    deploy = service.get("deploy")
    replicas = deploy.get("replicas") if isinstance(deploy, dict) else None
    if service.get("profiles") or service.get("scale") == 0 or replicas == 0:
        return set()
    argv: list[str] = []
    for key in ("entrypoint", "command"):
        value = service.get(key)
        if isinstance(value, list):
            argv.extend(str(item) for item in value)
        elif isinstance(value, str):
            try:
                argv.extend(shlex.split(value))  # how Compose splits a string command
            except ValueError:  # unbalanced quotes: read it as text
                argv.append(value)
    line = " ".join(argv)
    found = {name for name, words in _SHELL_WORDS.items() if words.search(line)}
    at = next((i for i in range(len(argv)) if argv[i : i + 3] == ["terp", "jobs", "worker"]), None)
    if at is not None and not (
        "--forever" in argv[at + 3 :] or service.get("restart") in _LOOPING_RESTARTS
    ):
        found.discard("terp-worker")  # a single drain that exits, and stays exited
    return found


def _load(path: pathlib.Path) -> tuple[Any, str | None]:
    import yaml

    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")), None
    except (OSError, yaml.YAMLError) as exc:
        return None, (
            f"profile: {path.name} could not be read, so what it deploys cannot be "
            f"established: {' '.join(str(exc).split())}"
        )


def _services(compose: Any) -> dict[str, Any]:
    services = compose.get("services") if isinstance(compose, dict) else None
    return services if isinstance(services, dict) else {}


def _named(names: Sequence[str]) -> str:
    shown = ", ".join(names[:_SHOWN])
    return f"{shown} and {len(names) - _SHOWN} more" if len(names) > _SHOWN else shown


def _remedy(role: str, *, terp: bool, celery: str | None) -> str:
    """How to add the *role* service: Terp's own command first, then the Celery engine's."""
    argv, celery_command = _COMMANDS[role]
    said = []
    if terp:
        said.append(
            f"Add a service on the backend image with `command: {argv}` (an image's CMD is "
            "not read: the command must be written in the profile), re-render the template "
            "(`copier update`), whose profile runs both the worker and the scheduler, or, "
            f'under "build": "generated", declare a unit with "role": "{role}" in '
            "deployment.json and run `uv run terp deployment render`."
        )
    if celery:
        said.append(
            f"{'Or run' if terp else 'Run'} {celery} as a service: "
            f"`celery -A <your celery app> {celery_command}`."
        )
    return " ".join(said)


def _overlay_problem(project_root: pathlib.Path, services: dict[str, Any]) -> str | None:
    """The services the runtime-role overlay names and the profile does not define."""
    path = project_root / RUNTIME_ROLE_OVERLAY
    if not path.is_file():
        return None
    overlay, unreadable = _load(path)
    missing = [name for name in _services(overlay) if name not in services]
    if unreadable or not missing:
        return unreadable
    listed = ", ".join(f"`{name}`" for name in missing)
    return (
        f"profile: {RUNTIME_ROLE_OVERLAY} names {listed}, which {PROD_PROFILE} does not "
        f'define, so Compose refuses the stack (service "{missing[0]}" has neither an image '
        'nor a build context specified). Under "build": "generated", declare the missing '
        'units in deployment.json and run `uv run terp deployment render`; under "build": '
        f'"own", re-render the template (`copier update`) or add the services to {PROD_PROFILE}.'
    )


def _worker_problem(jobs: Sequence[str], *, outbox: bool, celery: bool) -> str:
    runners = [
        *(["`terp jobs worker --forever`"] if outbox else []),
        *(["a Celery worker"] if celery else []),
    ]
    return (
        f"jobs: the control plane declares {len(jobs)} job(s) ({_named(jobs)}) and no service "
        f"in {PROD_PROFILE} runs {' or '.join(runners)}, so a job enqueued on the app's "
        "durable queue is never run, and nothing at boot says so. "
        + _remedy("worker", terp=outbox, celery="a Celery worker" if celery else None)
    )


def profile_problems(
    project_root: pathlib.Path, plane: ControlPlane
) -> tuple[list[str], str | None, list[str]]:
    """``(problems, note, runs)``: what the profile lacks, the note when there is no profile
    to read, and the processes it was found to run for the declared work."""
    from terp.cli.verify import NOTE_PREFIX

    jobs = [job.name for job in plane.jobs.jobs]
    schedules = [schedule.name for schedule in plane.schedules.schedules]
    outbox, celery = _installed(OUTBOX), _installed(CELERY_JOBS)
    need_worker = bool(jobs) and (outbox or celery)
    needed = [
        role
        for role, need in (("the worker", need_worker), ("the scheduler", bool(schedules)))
        if need
    ]
    profile = project_root / PROD_PROFILE
    if not profile.is_file():
        note = (
            f"{NOTE_PREFIX}no {PROD_PROFILE} - whether a service runs {' and '.join(needed)} "
            "the declared work needs was not judged: which process runs it is the deploy "
            "tool's business (ADR 0184)"
        )
        return [], note if needed else None, []
    if not needed and not (project_root / RUNTIME_ROLE_OVERLAY).is_file():
        return [], None, []
    compose, unreadable = _load(profile)
    if unreadable:
        return [unreadable], None, []
    services = _services(compose)
    problems = [problem for problem in (_overlay_problem(project_root, services),) if problem]
    running = set().union(*(_runs(s) for s in services.values() if isinstance(s, dict)))
    accepted = {*(["terp-worker"] if outbox else []), *(["celery-worker"] if celery else [])}
    runs: list[str] = []
    if need_worker and running & accepted:
        runs.append("worker")
    elif need_worker:
        problems.append(_worker_problem(jobs, outbox=outbox, celery=celery))
    if schedules and running & {"terp-scheduler", "celery-beat"}:
        runs.append("scheduler")
        if "terp-scheduler" in running and not _installed(APSCHEDULER):
            problems.append(
                f"schedules: {PROD_PROFILE} runs `terp jobs scheduler` for "
                f"{len(schedules)} declared schedule(s) ({_named(schedules)}) and "
                "terp-cap-scheduler-apscheduler is not installed, so that scheduler stops at "
                "start and restarts in a loop, and no schedule fires. Install it (`uv add "
                "terp-cap-scheduler-apscheduler`), or run the schedules on Celery beat."
            )
    elif schedules:
        beat = "Celery beat" if _installed(CELERY_BEAT) else None
        problems.append(
            f"schedules: the control plane declares {len(schedules)} schedule(s) "
            f"({_named(schedules)}) and no service in {PROD_PROFILE} runs `terp jobs "
            "scheduler` or Celery beat, so no declared schedule ever fires, and nothing at "
            "boot says so. " + _remedy("scheduler", terp=True, celery=beat)
        )
    return problems, None, runs


def declared_work_verdict(
    project_root: pathlib.Path, plane: ControlPlane
) -> Callable[[int, str], tuple[int, str]]:
    """Fold this half into the production-readiness lane's verdict on the boot half.

    The returned function takes the boot half's ``(exit_code, output)``. What the profile
    lacks follows the boot refusals as a section of its own, since the boot refusals'
    sentence (each raises ``BootError``) is not true of it, and with no boot refusal it is
    the whole output. The note that this half was not judged is kept in either verdict; a
    green otherwise names the processes it found.
    """
    problems, note, runs = profile_problems(project_root, plane)
    red = (
        f"{PROD_PROFILE} would not run this app as declared (ADR 0223):\n"
        + "\n".join(f"  {problem}" for problem in problems)
        if problems
        else ""
    )

    def finish(exit_code: int, output: str) -> tuple[int, str]:
        if exit_code or red:
            parts = (output if exit_code else "", red, note or "")
            return exit_code or 1, "\n".join(part for part in parts if part)
        if note is not None:
            return 0, f"{note}\n{output}"
        if runs:
            return 0, f"{output}, and {PROD_PROFILE} runs the " + " and the ".join(runs)
        return 0, output

    return finish


__all__ = [
    "PROD_PROFILE",
    "RUNTIME_ROLE_OVERLAY",
    "declared_work_verdict",
    "profile_problems",
]
