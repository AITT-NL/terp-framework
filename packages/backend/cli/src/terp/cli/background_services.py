"""Does the production profile run a process for the work the control plane declares?

The profile half of ``terp verify --only production-readiness`` (ADR 0223). A declared job
needs a service of ``docker-compose.prod.yml`` running ``terp jobs worker``, and a declared
schedule one running ``terp jobs scheduler``. Without them the API starts and reports
healthy while the work does not happen, and nothing refuses that state at any boot, so it is
reported apart from the boot refusals, with its own closing sentence.

Asked only when the plane declares work, so an app without jobs is unaffected. A project with
no ``docker-compose.prod.yml`` is deployed some other way, and which process runs its work is
the deploy tool's business (ADR 0184): a note, never a red. A profile that does not parse is a
red, as it is in ``deploy-safety``: nothing in it can be shown to run anything. One that
parses to no services runs none, and is judged so.
"""

from __future__ import annotations

import pathlib
import re
from collections.abc import Callable
from typing import Any

from terp.core import ControlPlane

#: The production profile read for the processes, the file ``deploy-safety`` audits.
PROD_PROFILE = "docker-compose.prod.yml"

#: What counts as running each process, searched in a service's entrypoint and command
#: read as one line. The argument list the generator renders and ``uv run terp ...`` both
#: hold the words, and so does the shell loop older profiles wrapped around a single drain,
#: which runs the work as surely. Celery counts too: a Celery worker and Celery beat are the
#: other engines the jobs seam ships (``terp-cap-jobs-celery``,
#: ``terp-cap-scheduler-celery-beat``), and a worker started with ``-B`` runs beat as well.
_RUNS = {
    "worker": re.compile(r"\bterp\s+jobs\s+worker\b|\bcelery\b.*\sworker\b"),
    "scheduler": re.compile(
        r"\bterp\s+jobs\s+scheduler\b|\bcelery\b.*(\sbeat\b|\s-B\b|\s--beat\b)"
    ),
}


def _command_line(service: dict[str, Any]) -> str:
    """A compose service's entrypoint and command as one line, list or string form alike."""
    parts: list[str] = []
    for key in ("entrypoint", "command"):
        value = service.get(key)
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, list):
            parts.extend(str(item) for item in value)
    return " ".join(parts)


def work_without_a_process(
    project_root: pathlib.Path, *, jobs: int, schedules: int
) -> tuple[list[str], str | None]:
    """The declared work no service of the production profile runs: ``(problems, note)``."""
    if not jobs and not schedules:
        return [], None
    import yaml

    from terp.arch.deployment.profile import services_of
    from terp.cli.verify import NOTE_PREFIX

    path = project_root / PROD_PROFILE
    if not path.is_file():
        return [], (
            f"{NOTE_PREFIX}no {PROD_PROFILE} - whether a service runs the worker and the "
            "scheduler the declared work needs was not judged: which process runs it is the "
            "deploy tool's business (ADR 0184)"
        )
    try:
        compose = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return [
            f"profile: {PROD_PROFILE} could not be read, so no service in it can be shown "
            f"to run the declared work: {' '.join(str(exc).split())}"
        ], None
    lines = [
        _command_line(service)
        for service in (services_of(compose) if isinstance(compose, dict) else {}).values()
    ]
    problems: list[str] = []
    for label, count, noun, role, consequence, aside in (
        (
            "jobs",
            jobs,
            "job(s)",
            "worker",
            "a job enqueued on the durable outbox is never run",
            " Where terp-cap-outbox is not installed the worker idles, so it costs nothing "
            "until there is work.",
        ),
        (
            "schedules",
            schedules,
            "schedule(s)",
            "scheduler",
            "no declared schedule ever fires",
            "",
        ),
    ):
        if count and not any(_RUNS[role].search(line) for line in lines):
            problems.append(
                f"{label}: the control plane declares {count} {noun} and no service in "
                f"{PROD_PROFILE} runs `terp jobs {role}`, so {consequence} while this "
                f"gate is green. Add the `{role}` service: re-render the template "
                "(`copier update`), whose profile runs both the worker and the scheduler, "
                f'or, under "build": "generated", declare a unit with "role": "{role}" in '
                f"deployment.json and run `uv run terp deployment render`.{aside}"
            )
    return problems, None


def declared_work_verdict(
    project_root: pathlib.Path, plane: ControlPlane
) -> Callable[[int, str], tuple[int, str]]:
    """Fold this half into the production-readiness lane's verdict on the boot half.

    The returned function takes the boot half's ``(exit_code, output)``. The work no service
    runs follows the boot refusals as a section of its own, with its own closing sentence,
    since the boot refusals' sentence (each raises ``BootError``) is not true of it; with no
    boot refusal it is the whole output. A green leads with the note when this half was not
    judged, and otherwise names the processes it found.
    """
    jobs, schedules = len(plane.jobs.jobs), len(plane.schedules.schedules)
    unrun, note = work_without_a_process(project_root, jobs=jobs, schedules=schedules)
    red = (
        f"the work this app declares has no process in {PROD_PROFILE} to run it:\n"
        + "".join(f"  {problem}\n" for problem in unrun)
        + "Nothing refuses this at boot: the API starts and reports healthy, so this gate "
        "is the one place it shows (ADR 0223)."
        if unrun
        else ""
    )
    runs = [role for role, count in (("worker", jobs), ("scheduler", schedules)) if count]

    def finish(exit_code: int, output: str) -> tuple[int, str]:
        if exit_code:
            return exit_code, (f"{output}\n{red}" if red else output)
        if red:
            return 1, red
        if note is not None:
            return 0, f"{note}\n{output}"
        if runs:
            return 0, f"{output}, and {PROD_PROFILE} runs the " + " and the ".join(runs)
        return 0, output

    return finish


__all__ = ["PROD_PROFILE", "declared_work_verdict", "work_without_a_process"]
