"""``terp jobs`` — run a job (the external-scheduler trigger) and inspect the catalog.

The jobs seam (ADR 0043) is driven from the CLI two ways:

* ``terp jobs run <name> --payload <json>`` is the most abstract possible scheduler —
  any cron / k8s CronJob / systemd timer / Azure timer invokes it, so a scheduled job
  works today with zero broker infra. It builds the app (so ``create_app`` has configured
  the live :class:`~terp.core.JobCatalog` + queue), resolves the named job, validates the
  JSON payload against its schema, and enqueues it through the typed
  :func:`terp.core.enqueue` chokepoint.
* ``terp jobs list`` / ``terp inspect jobs`` render the registered jobs straight from the
  control plane's catalog (like ``terp inspect control-plane`` renders the authority map),
  so the listing is generated and cannot drift from what the app actually runs.
* ``terp jobs worker --forever`` and ``terp jobs scheduler`` are the two long-running
  processes. Each writes a heartbeat its container's healthcheck reads
  (:mod:`terp.cli.heartbeat`, ADR 0191), and each stops cleanly on SIGTERM or SIGINT: the
  worker finishes the job it is running and releases the rest of its batch, the
  scheduler lets the ticks in flight finish. Where there is provably nothing to do (no
  outbox installed for the worker; no schedule declared and no engine installed for the
  scheduler) each idles instead of exiting, beating until it is stopped (ADR 0223).
"""

from __future__ import annotations

import contextlib
import importlib
import json
import logging
import pathlib
import signal
import sys
import textwrap
from collections.abc import Callable, Iterator
from threading import Event

from fastapi import FastAPI

from terp.core import ControlPlane, enqueue, is_durable_schedule_ledger
from terp.core.db import get_session
from terp.core.jobs import active_job_catalog

from terp.cli.heartbeat import (
    SCHEDULER_BEAT_SECONDS,
    SCHEDULER_STALE_AFTER,
    Heartbeat,
    worker_stale_after,
)

_logger = logging.getLogger("terp.cli.jobs")


@contextlib.contextmanager
def _on_stop(handler: Callable[[], None]) -> Iterator[None]:
    """Run *handler* on SIGTERM or SIGINT for the block; the previous handlers come back after."""
    previous = {
        number: signal.signal(number, lambda _signum, _frame: handler())
        for number in (signal.SIGTERM, signal.SIGINT)
    }
    try:
        yield
    finally:
        for number, restored in previous.items():
            signal.signal(number, restored)


def _idle(heartbeat: Heartbeat, stopping: Event, *, every: float) -> None:
    """Beat every *every* seconds until SIGTERM or SIGINT sets *stopping* (ADR 0223).

    The process has provably nothing to do. Exiting instead would be a restart loop under
    ``restart: unless-stopped``, which ``docker compose up --wait`` reads as a failed deploy,
    so it waits as a healthy idle process waits: its heartbeat fresh, its healthcheck green.
    The heartbeat goes with the process.
    """
    try:
        with _on_stop(stopping.set):
            while not stopping.is_set():
                heartbeat.beat()
                stopping.wait(every)
    finally:
        heartbeat.clear()


def _absent(exc: ImportError, *modules: str) -> bool:
    """Whether *exc* says one of *modules* is not installed, rather than broken.

    Only a missing module that is one of them, or a parent of one, counts. A capability
    that is installed and fails to import (a dependency of its own missing, a name it no
    longer exports) is raised as it is: idling over it, or calling it not installed, would
    hide the error an operator has to read.
    """
    name = exc.name if isinstance(exc, ModuleNotFoundError) else None
    return name is not None and any(m == name or m.startswith(f"{name}.") for m in modules)


def _load_control_plane(dotted: str) -> ControlPlane:
    """Resolve a ``module:attribute`` reference to a :class:`~terp.core.ControlPlane`."""
    module_name, _, attr = dotted.partition(":")
    if not module_name:
        raise SystemExit(f"{dotted!r} is not a valid 'module:attribute' reference")
    module = importlib.import_module(module_name)
    candidate = getattr(module, attr or "control_plane")
    if not isinstance(candidate, ControlPlane):
        raise SystemExit(f"{dotted!r} did not resolve to a terp.core.ControlPlane instance")
    return candidate


def _load_app(dotted: str) -> FastAPI:
    """Resolve a ``module:attribute`` reference to a FastAPI app (instance or factory).

    Building the app runs ``create_app``, which configures the live job catalog + queue —
    so ``terp jobs run`` enqueues against exactly what the app would run. Mirrors the
    ``terp openapi`` loader.
    """
    module_name, _, attr = dotted.partition(":")
    if not module_name:
        raise SystemExit(f"{dotted!r} is not a valid 'module:attribute' reference")
    module = importlib.import_module(module_name)
    candidate = getattr(module, attr or "app")
    if isinstance(candidate, FastAPI):
        return candidate
    if callable(candidate):
        built = candidate()
        if isinstance(built, FastAPI):
            return built
    raise SystemExit(f"{dotted!r} did not resolve to a FastAPI application")


def render_jobs(dotted: str = "control_plane:control_plane") -> str:
    """Render the control plane's registered jobs (the ``jobs list`` / ``inspect jobs`` view).

    Generated from the live :class:`~terp.core.JobCatalog`, so it always matches what the
    app declares — name, routing queue, retry budget, and visibility — plus the configured
    system actor a user-less job runs as, or, when jobs are declared and no actor is, the
    reason a production boot refuses that (ADR 0125).
    """
    plane = _load_control_plane(dotted)
    lines = ["Jobs"]
    if not plane.jobs.jobs:
        lines.append("  <none declared>")
    for job in sorted(plane.jobs.jobs, key=lambda item: item.name):
        lines.append(
            f"  {job.name}  queue={job.queue}  visibility={job.visibility.value}  "
            f"retry={job.retry.max_attempts}x"
        )
    if plane.job_system_actor_id is not None:
        lines.append("")
        lines.append(f"System actor: {plane.job_system_actor_id}")
    else:
        # This surface used to be silent in exactly the state that now refuses a
        # production boot (ADR 0125), which made it the last place an operator would
        # learn about it. The boot check's own sentence is reused rather than
        # paraphrased, so the two cannot drift -- and it stays quiet when nothing is
        # declared, because then there is nothing to refuse.
        for problem in plane.production_problems():
            lines.append("")
            lines.append("System actor: NONE")
            # Wrapped and indented because a BootError is read once, in a log, while
            # this is read by someone deciding whether to deploy -- a single 300-column
            # line is the same information nobody finishes reading.
            lines.extend(
                textwrap.wrap(
                    problem[:1].upper() + problem[1:],
                    width=88,
                    initial_indent="  ",
                    subsequent_indent="  ",
                )
            )
    return "\n".join(lines)


def run_job_command(
    name: str,
    *,
    payload: str = "{}",
    app_ref: str = "app.main:app",
    app_root: str | pathlib.Path = ".",
) -> str:
    """Build *app_ref*, resolve job *name*, validate *payload* JSON, and enqueue it.

    *app_root* is placed first on ``sys.path`` so the app package imports when ``terp`` runs
    as an installed console script. An unknown job name or malformed JSON fails closed with
    a ``SystemExit`` (a clean CLI error), and the payload is validated against the job's
    schema before enqueuing, so a bad trigger never reaches a handler.
    """
    root = str(pathlib.Path(app_root).resolve())
    if root not in sys.path:
        sys.path.insert(0, root)
    _load_app(app_ref)
    job = active_job_catalog().get(name)
    if job is None:
        raise SystemExit(
            f"job {name!r} is not registered in the app's JobCatalog; "
            f"run `terp jobs list` to see the declared jobs"
        )
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"--payload is not valid JSON: {exc}") from exc
    payload_obj = job.payload_schema.model_validate(data)
    with contextlib.closing(get_session()) as gen:
        session = next(gen)
        job_id = enqueue(session, job=job, payload=payload_obj)
    return f"enqueued {name!r} (job id {job_id})"


def run_worker_command(
    *,
    app_ref: str = "app.main:app",
    app_root: str | pathlib.Path = ".",
    max_cycles: int | None = None,
    batch_size: int = 10,
    lease_seconds: float = 30.0,
    forever: bool = False,
    poll_seconds: float = 5.0,
    stop: Event | None = None,
    heartbeat_path: pathlib.Path | None = None,
) -> str:
    """Build *app_ref*, then drain the durable outbox until empty (or *max_cycles*).

    The worker-container entrypoint (ADR 0045). Building the app runs ``create_app``, so the
    live :class:`~terp.core.JobCatalog` is configured (the worker's ``run_job`` resolves each
    job by name) and the durable :class:`~terp.capabilities.outbox.OutboxJobQueue` is wired.
    It then leases due ``outbox_message`` rows, runs jobs through the context-binding kernel
    runner and events through the in-process handlers, and retries / dead-letters per each
    job's :class:`~terp.core.RetryPolicy`. ``SKIP LOCKED`` is enabled automatically on
    PostgreSQL; on SQLite the portable atomic-UPDATE lease is used. Requires the
    ``terp-cap-outbox`` capability (an app wiring the durable queue already depends on
    it; a standalone worker image installs ``terp-cli[worker]`` or the combined
    ``terp-cli[jobs]`` extra).

    *forever* is the worker container's command (ADR 0187): drain, wait *poll_seconds*,
    drain again, until SIGTERM or SIGINT. It replaces the shell loop a profile used to wrap
    around a single drain, so a generated profile renders an argument list rather than a
    shell string. A stop claims nothing more: the job running finishes, and the rest of its
    batch is released for another worker at once (ADR 0191). *stop* is the event the
    signals set, injectable for tests; the previous handlers are restored on exit.

    Under *forever* the worker writes its heartbeat (:mod:`terp.cli.heartbeat`) before
    each claim, after each job and between drains, allowed to grow
    ``max(lease_seconds, poll_seconds)`` plus a grace before its healthcheck calls it
    stuck. *heartbeat_path* moves the file, for tests; the container's healthcheck reads the
    default.

    Under *forever* in an app that does not install ``terp-cap-outbox``, the worker idles
    instead of exiting (ADR 0223): the app keeps no outbox, so nothing could ever reach it.
    It says so in one log line, beats every *poll_seconds* and waits for the stop signal,
    because the production profile runs a worker in every app and an exit there is a restart
    loop. The single drain keeps refusing without the capability: whoever runs it by hand
    wants to know.
    """
    heartbeat = (
        Heartbeat(
            "worker",
            stale_after=worker_stale_after(lease_seconds=lease_seconds, poll_seconds=poll_seconds),
            path=heartbeat_path,
        )
        if forever
        else None
    )
    if heartbeat is not None:
        heartbeat.clear()
    root = str(pathlib.Path(app_root).resolve())
    if root not in sys.path:
        sys.path.insert(0, root)
    _load_app(app_ref)

    try:
        from terp.capabilities.outbox import OutboxWorker
    except ImportError as exc:
        if not _absent(exc, "terp.capabilities.outbox"):
            raise
        if heartbeat is not None:
            declared = len(active_job_catalog().jobs)
            _logger.info(
                "terp jobs worker idles: terp-cap-outbox is not installed, so this app keeps "
                "no outbox and there is nothing to drain%s. Install terp-cap-outbox and wire "
                "create_app(job_queue=OutboxJobQueue()) to give it work (ADR 0223).",
                f"; its {declared} declared job(s) run where its job queue runs them, inline "
                "on the default queue" if declared else "",
            )
            _idle(heartbeat, stop if stop is not None else Event(), every=poll_seconds)
            return (
                "outbox worker idled until stopped: terp-cap-outbox is not installed, "
                "so there was no outbox to drain"
            )
        raise SystemExit(
            "terp jobs worker requires the terp-cap-outbox capability, which is not "
            "installed. Add terp-cap-outbox to the app's dependencies (wiring the "
            "durable OutboxJobQueue already requires it) or install `terp-cli[worker]` "
            "(or `terp-cli[jobs]` for worker + scheduler support)."
        ) from exc
    from terp.cli._engine import cli_engine, cli_session_factory

    engine = cli_engine()
    worker = OutboxWorker(
        cli_session_factory(engine),
        batch_size=batch_size,
        lease_seconds=lease_seconds,
        skip_locked=engine.dialect.name == "postgresql",
    )
    if heartbeat is None:
        return f"outbox worker drained: {_tally([worker.run(max_cycles=max_cycles)])}"
    stopping = stop if stop is not None else Event()
    results: list[object] = []
    try:
        with _on_stop(stopping.set):
            while not stopping.is_set():
                # The drain beats before each claim and after each job, so an idle worker
                # beats once per pass and a worker stuck in one job not at all.
                results.append(
                    worker.run(max_cycles=max_cycles, stop=stopping, beat=heartbeat.beat)
                )
                stopping.wait(poll_seconds)
    finally:
        heartbeat.clear()
    return f"outbox worker stopped after {len(results)} pass(es): {_tally(results)}"


def _tally(results: list[object]) -> str:
    """The drain counts of every pass, summed, in the order the worker reports them."""
    fields = ("claimed", "dispatched", "retried", "dead_lettered", "lost", "released")
    return " ".join(
        f"{name.replace('_', '-')}={sum(getattr(result, name) for result in results)}"
        for name in fields
    )


#: The modules the default scheduler engine is made of.
_SCHEDULER_ENGINE = ("apscheduler.schedulers.blocking", "terp.capabilities.scheduler_apscheduler")


def _scheduler_engine() -> tuple[type, type]:
    """The default engine's two parts: APScheduler's blocking scheduler and Terp's adapter.

    Raises ``ImportError`` when ``terp-cap-scheduler-apscheduler`` is not installed.
    """
    from apscheduler.schedulers.blocking import BlockingScheduler

    from terp.capabilities.scheduler_apscheduler import ApschedulerScheduler

    return BlockingScheduler, ApschedulerScheduler


def _scheduler_engine_installed() -> bool:
    """Whether the default engine (``terp-cap-scheduler-apscheduler``) is installed."""
    try:
        _scheduler_engine()
    except ImportError as exc:
        if not _absent(exc, *_SCHEDULER_ENGINE):
            raise
        return False
    return True


def _default_scheduler() -> object:
    """Build the default scheduler process: a blocking APScheduler wrapped by the adapter.

    A dedicated ``terp jobs scheduler`` process runs APScheduler's ``BlockingScheduler`` (its
    ``start`` blocks the main thread), driving each schedule's tick through the jobs seam.
    Requires the ``terp-cap-scheduler-apscheduler`` capability.
    """

    try:
        blocking, adapter = _scheduler_engine()
    except ImportError as exc:
        if not _absent(exc, *_SCHEDULER_ENGINE):
            raise
        raise SystemExit(
            "terp jobs scheduler requires the terp-cap-scheduler-apscheduler "
            "capability, which is not installed. Add terp-cap-scheduler-apscheduler "
            "to the app's dependencies, install `terp-cli[scheduler]` (or the combined "
            "`terp-cli[jobs]` extra), or run schedules with Celery beat."
        ) from exc
    from terp.cli._engine import cli_engine, cli_session_factory

    engine = cli_engine()
    return adapter(cli_session_factory(engine), scheduler=blocking())


def run_scheduler_command(
    *,
    app_ref: str = "app.main:app",
    app_root: str | pathlib.Path = ".",
    scheduler: object | None = None,
    heartbeat_path: pathlib.Path | None = None,
    stop: Event | None = None,
) -> str:
    """Build *app_ref*, then run the in-process scheduler until stopped (the scheduler entrypoint).

    The scheduler-process entrypoint deferred from ADR 0048: building the app runs ``create_app``,
    so the live :class:`~terp.core.ScheduleCatalog` (and the :class:`~terp.core.JobCatalog` its
    jobs resolve against) is configured. It registers every declared schedule with an
    APScheduler-backed :class:`~terp.core.Scheduler` and starts it — each cron tick fires the
    schedule through the typed :func:`~terp.core.enqueue` chokepoint, so a scheduled job flows
    through the active :class:`~terp.core.JobQueue` (run it off-request with ``terp jobs worker``
    when the durable outbox is wired). ``start`` **blocks** until the process is stopped.
    *scheduler* is injectable for tests; the default wraps a blocking APScheduler and requires the
    ``terp-cap-scheduler-apscheduler`` capability.

    Before the engine runs, ``start`` settles every schedule against the app's
    :class:`~terp.core.ScheduleLedger`, so a cron time that passed while no scheduler ran is
    run once late or recorded skipped, as the schedule declares (ADR 0191). A ledger that is
    not durable is named in the log, because then the gap is never seen. The scheduler
    beats every few seconds from its own engine (:mod:`terp.cli.heartbeat`;
    *heartbeat_path* moves the file, for tests), and SIGTERM or SIGINT shut the engine down
    once the ticks in flight have finished. *stop* is the event the signals set, injectable
    for tests.

    An app that declares no schedule and installs no engine has provably nothing to fire, so
    the scheduler idles instead of exiting (ADR 0223): one log line, a heartbeat every
    ``SCHEDULER_BEAT_SECONDS`` against the same bound, and a wait for the stop signal, because
    the production profile runs a scheduler in every app and an exit there is a restart loop.
    A declared schedule with no engine still refuses, naming the package: there is work, and
    nothing would do it.
    """
    heartbeat = Heartbeat("scheduler", stale_after=SCHEDULER_STALE_AFTER, path=heartbeat_path)
    heartbeat.clear()
    root = str(pathlib.Path(app_root).resolve())
    if root not in sys.path:
        sys.path.insert(0, root)
    _load_app(app_ref)

    from terp.core.scheduling import active_schedule_catalog, active_schedule_ledger

    catalog = active_schedule_catalog()
    stopping = stop if stop is not None else Event()
    if scheduler is None and not catalog.schedules and not _scheduler_engine_installed():
        _logger.info(
            "terp jobs scheduler idles: this app declares no schedule and "
            "terp-cap-scheduler-apscheduler is not installed, so there is nothing to fire. "
            "Declare a schedule on the control plane and install "
            "terp-cap-scheduler-apscheduler to give it work (ADR 0223)."
        )
        _idle(heartbeat, stopping, every=SCHEDULER_BEAT_SECONDS)
        return (
            "scheduler idled until stopped: no schedule declared and "
            "terp-cap-scheduler-apscheduler is not installed"
        )
    if catalog.schedules and not is_durable_schedule_ledger(active_schedule_ledger()):
        _logger.warning(
            "the schedule ledger is per process: a cron time that passes while no scheduler "
            "runs is never seen, so no misfire policy can apply to it. Wire "
            "create_app(schedule_ledger=DatabaseScheduleLedger()) from terp-cap-outbox "
            "(ADR 0191)."
        )
    scheduler = scheduler if scheduler is not None else _default_scheduler()
    scheduler.register_all(catalog)
    every = getattr(scheduler, "every", None)
    if callable(every):
        every(SCHEDULER_BEAT_SECONDS, heartbeat.beat)
    names = ", ".join(catalog.names()) or "<none>"

    def _stop() -> None:
        # Once: a second signal while the engine shuts down must not ask it again.
        if not stopping.is_set():
            stopping.set()
            scheduler.shutdown(wait=True)

    try:
        with _on_stop(_stop):
            scheduler.start()  # blocks until the process is stopped (a long-running daemon)
    finally:
        heartbeat.clear()
    return f"scheduler stopped; {len(catalog.schedules)} schedule(s) registered: {names}"


__all__ = [
    "render_jobs",
    "run_job_command",
    "run_scheduler_command",
    "run_worker_command",
]
