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
* a declared schedule needs ``terp jobs scheduler`` where ``terp-cap-scheduler-apscheduler``
  is installed, Celery beat where ``terp-cap-scheduler-celery-beat`` is, either where both
  are. Beat only publishes a tick for each cron time and a Celery worker runs it, so where
  beat is the one that counts, a Celery worker must run as well (``worker -B`` is both).
  Where only beat is installed, ``terp jobs scheduler`` idles, so it neither counts nor
  harms; where neither is, it stops at start, and the remedy starts with installing one.

A service counts only when a plain ``docker compose up`` starts it and keeps it running: not
one under ``profiles``, scaled to 0 (``scale`` or ``deploy.replicas``), with a string command
Compose cannot split, nor ``terp jobs worker`` as an argument list without ``--forever``
that nothing restarts after a clean exit (``deploy.restart_policy`` before ``restart``, as
Compose reads them), which is a single drain. A shell string is read only for the words: one
that names ``terp jobs worker`` counts, as older profiles wrapped a single drain in a shell
loop, and what that shell really runs is a residual this check cannot read. A ``celery``
command is read by its subcommand, past its options and their values (``-A worker.app beat``
runs beat alone).

Independent of declared work, ``compose.runtime-role.yml`` must not name a service the
profile does not define: Compose refuses that stack. It is how a generated build meets a
template update whose overlay names a ``worker`` its own profile has not rendered yet.

Only ``docker-compose.prod.yml`` and that overlay are read, with the Compose-aware loader of
``terp.arch.deployment.profile`` (its ``!reset`` and ``!override`` tags), as ``deploy-safety``
reads the one file: not the ``compose.file`` or ``compose.overrides`` a ``deployment.json``
may name, so a worker added in an override reads as missing. A project with no
``docker-compose.prod.yml`` is deployed some other way, and which process runs its work is
the deploy tool's business (ADR 0184): a note, never a red. A file that does not parse is a
red, as in ``deploy-safety``, and so is one that holds no mapping, which the loader refuses
as Compose would; one with no services runs none.
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
}
#: Celery's options before its subcommand that take the next word as their value.
_CELERY_VALUED = frozenset(
    {"-A", "--app", "-b", "--broker", "--result-backend", "--loader", "--config", "--workdir"}
)
_LOOPING_RESTARTS = ("always", "unless-stopped")
_SHOWN = 5
_CELERY = "`celery -A <your celery app> {}`"
#: Each role's Terp command, and the Celery processes that do its work instead.
_COMMANDS = {
    "worker": ('["terp", "jobs", "worker", "--forever"]', _CELERY.format("worker")),
    "scheduler": (
        '["terp", "jobs", "scheduler"]',
        f"{_CELERY.format('beat')}, with a Celery worker to run its ticks, "
        f"{_CELERY.format('worker')} (or both in one service, {_CELERY.format('worker -B')})",
    ),
}
_APSCHEDULER_DIST = "terp-cap-scheduler-apscheduler"


def installed(module: str) -> bool:
    """Whether *module* is installed in this environment, found without importing it."""
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def _restarts(service: dict[str, Any]) -> bool:
    """Whether Compose starts *service* again after a clean exit."""
    deploy = service.get("deploy")
    policy = deploy.get("restart_policy") if isinstance(deploy, dict) else None
    if isinstance(policy, dict):  # set, it is read instead of `restart`
        return policy.get("condition", "any") == "any"
    return service.get("restart") in _LOOPING_RESTARTS


def _celery(words: Sequence[str]) -> set[str]:
    """What a ``celery`` command in *words* runs, read from its subcommand as a whole word.

    After the ``celery`` executable come its options, then the subcommand: ``worker`` runs a
    worker, and beat as well with ``-B``/``--beat``; ``beat`` runs beat. An option's value
    (``-A worker.celery``) is skipped, so a name that merely contains the word is not read
    as the subcommand.
    """
    for start, word in enumerate(words):
        if pathlib.PurePosixPath(word).name != "celery":
            continue
        at = start + 1
        while at < len(words) and words[at].startswith("-"):
            at += 2 if words[at] in _CELERY_VALUED else 1
        subcommand, options = words[at] if at < len(words) else None, set(words[at + 1 :])
        if subcommand == "beat":
            return {"celery-beat"}
        if subcommand == "worker":
            return {"celery-worker", *(["celery-beat"] if options & {"-B", "--beat"} else [])}
    return set()


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
            except ValueError:  # unbalanced quotes: Compose refuses the service, too
                return set()
    found = {name for name, words in _SHELL_WORDS.items() if words.search(" ".join(argv))}
    # The argument list first; failing that, a shell string inside it (`sh -c "celery …"`).
    found |= _celery(argv) or set().union(*(_celery(word.split()) for word in argv if " " in word))
    at = next(
        (
            index
            for index, word in enumerate(argv)
            if pathlib.PurePosixPath(word).name == "terp"
            and argv[index + 1 : index + 3] == ["jobs", "worker"]
        ),
        None,
    )
    if at is not None and "--forever" not in argv[at + 3 :] and not _restarts(service):
        found.discard("terp-worker")  # a single drain that exits, and stays exited
    return found


def _load(path: pathlib.Path) -> tuple[dict[str, Any], str | None]:
    from terp.arch.deployment.profile import profile_from_text

    compose, findings = profile_from_text(path.read_text(encoding="utf-8"), path.name)
    if not findings:
        return compose, None
    said = " ".join(findings[0].message.removeprefix("compose.file ").split())
    return {}, f"profile: what {path.name} deploys cannot be established: {said}"


def _services(compose: dict[str, Any]) -> dict[str, Any]:
    services = compose.get("services")
    return services if isinstance(services, dict) else {}


def _named(names: Sequence[str]) -> str:
    shown = ", ".join(names[:_SHOWN])
    return f"{shown} and {len(names) - _SHOWN} more" if len(names) > _SHOWN else shown


def _remedy(role: str, *, terp: bool, celery: str | None, install: bool = False) -> str:
    """How to add the *role* service, led by the engine that is installed."""
    argv, celery_runs = _COMMANDS[role]
    said = []
    if terp:
        lead = (
            f"Install {_APSCHEDULER_DIST} (`uv add {_APSCHEDULER_DIST}`), then add"
            if install
            else "Add"
        )
        said.append(
            f"{lead} a service on the backend image with `command: {argv}` (an image's CMD "
            "is not read: the command must be written in the profile), re-render the "
            "template (`copier update`), whose profile runs both the worker and the "
            f'scheduler, or, under "build": "generated", declare a unit with "role": "{role}" '
            "in deployment.json and run `uv run terp deployment render`."
        )
    if celery:
        said.append(f"{'Or run' if terp else 'Run'} {celery} as a service: {celery_runs}.")
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
        f'"own", re-render the template (`copier update`), add the services to {PROD_PROFILE}, '
        "or point the overlay at your own service names and remove its entries for services "
        "you do not run."
    )


def _runners(*named: tuple[str, bool]) -> str:
    return " or ".join(name for name, present in named if present)


def _worker_problem(jobs: Sequence[str], *, outbox: bool, celery: bool) -> str:
    runners = _runners(("`terp jobs worker --forever`", outbox), ("a Celery worker", celery))
    return (
        f"jobs: the control plane declares {len(jobs)} job(s) ({_named(jobs)}) and no service "
        f"in {PROD_PROFILE} runs {runners}, so a job enqueued on the app's durable queue is "
        "never run, and nothing at boot says so. "
        + _remedy("worker", terp=outbox, celery="a Celery worker" if celery else None)
    )


def _scheduler_problem(schedules: Sequence[str], *, apscheduler: bool, beat: bool) -> str:
    terp = apscheduler or not beat
    runners = _runners(("`terp jobs scheduler`", terp), ("Celery beat", beat))
    return (
        f"schedules: the control plane declares {len(schedules)} schedule(s) "
        f"({_named(schedules)}) and no service in {PROD_PROFILE} runs {runners}, so no "
        "declared schedule ever fires, and nothing at boot says so. "
        + _remedy(
            "scheduler",
            terp=terp,
            celery="Celery beat" if beat else None,
            install=not apscheduler and not beat,
        )
    )


def profile_problems(
    project_root: pathlib.Path, plane: ControlPlane
) -> tuple[list[str], str | None, list[str]]:
    """``(problems, note, runs)``: what the profile lacks, the note when there is no profile
    to read, and the processes it was found to run for the declared work."""
    from terp.cli.verify import NOTE_PREFIX

    jobs = [job.name for job in plane.jobs.jobs]
    schedules = [schedule.name for schedule in plane.schedules.schedules]
    outbox, celery = installed(OUTBOX), installed(CELERY_JOBS)
    apscheduler, beat = installed(APSCHEDULER), installed(CELERY_BEAT)
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
    drains = {*(["terp-worker"] if outbox else []), *(["celery-worker"] if celery else [])}
    fires = {*(["terp-scheduler"] if apscheduler else []), *(["celery-beat"] if beat else [])}
    runs: list[str] = []
    if need_worker and running & drains:
        runs.append("worker")
    elif need_worker:
        problems.append(_worker_problem(jobs, outbox=outbox, celery=celery))
    if schedules and (running & fires) == {"celery-beat"} and "celery-worker" not in running:
        problems.append(
            f"schedules: {PROD_PROFILE} runs Celery beat for {len(schedules)} declared "
            f"schedule(s) ({_named(schedules)}) and no Celery worker, so nothing runs the "
            "ticks beat publishes, and nothing at boot says so. Run a Celery worker as a "
            f"service as well, {_CELERY.format('worker')}, or run beat inside it, "
            f"{_CELERY.format('worker -B')}."
        )
    elif schedules and running & fires:
        runs.append("scheduler")
    elif schedules and "terp-scheduler" in running and not beat:
        problems.append(
            f"schedules: {PROD_PROFILE} runs `terp jobs scheduler` for {len(schedules)} "
            f"declared schedule(s) ({_named(schedules)}) and {_APSCHEDULER_DIST} is not "
            "installed, so that scheduler stops at start (and, under a restart policy, "
            "restarts in a loop) and no schedule fires. Install it (`uv add "
            f"{_APSCHEDULER_DIST}`)."
        )
    elif schedules:
        problems.append(_scheduler_problem(schedules, apscheduler=apscheduler, beat=beat))
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
    "APSCHEDULER",
    "CELERY_BEAT",
    "CELERY_JOBS",
    "OUTBOX",
    "PROD_PROFILE",
    "RUNTIME_ROLE_OVERLAY",
    "declared_work_verdict",
    "installed",
    "profile_problems",
]
