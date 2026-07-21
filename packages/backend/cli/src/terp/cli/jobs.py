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
"""

from __future__ import annotations

import contextlib
import importlib
import json
import pathlib
import sys

from fastapi import FastAPI

from terp.core import ControlPlane, enqueue
from terp.core.db import get_session
from terp.core.jobs import active_job_catalog


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
    system actor a user-less job runs as.
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
    it; a standalone worker image installs ``terp-cli[jobs]``).
    """
    root = str(pathlib.Path(app_root).resolve())
    if root not in sys.path:
        sys.path.insert(0, root)
    _load_app(app_ref)

    from sqlmodel import Session

    try:
        from terp.capabilities.outbox import OutboxWorker
    except ImportError as exc:
        raise SystemExit(
            "terp jobs worker requires the terp-cap-outbox capability, which is not "
            "installed. Add terp-cap-outbox to the app's dependencies (wiring the "
            "durable OutboxJobQueue already requires it) or install `terp-cli[jobs]`."
        ) from exc
    from terp.core._internal.engine import get_engine

    engine = get_engine()
    worker = OutboxWorker(
        lambda: Session(engine),
        batch_size=batch_size,
        lease_seconds=lease_seconds,
        skip_locked=engine.dialect.name == "postgresql",
    )
    result = worker.run(max_cycles=max_cycles)
    return (
        f"outbox worker drained: claimed={result.claimed} dispatched={result.dispatched} "
        f"retried={result.retried} dead-lettered={result.dead_lettered} lost={result.lost}"
    )


def _default_scheduler() -> object:
    """Build the default scheduler process: a blocking APScheduler wrapped by the adapter.

    A dedicated ``terp jobs scheduler`` process runs APScheduler's ``BlockingScheduler`` (its
    ``start`` blocks the main thread), driving each schedule's tick through the jobs seam.
    Requires the ``terp-cap-scheduler-apscheduler`` capability.
    """
    from sqlmodel import Session

    try:
        from apscheduler.schedulers.blocking import BlockingScheduler

        from terp.capabilities.scheduler_apscheduler import ApschedulerScheduler
    except ImportError as exc:
        raise SystemExit(
            "terp jobs scheduler requires the terp-cap-scheduler-apscheduler "
            "capability, which is not installed. Add terp-cap-scheduler-apscheduler "
            "to the app's dependencies (or run schedules with Celery beat)."
        ) from exc
    from terp.core._internal.engine import get_engine

    engine = get_engine()
    return ApschedulerScheduler(lambda: Session(engine), scheduler=BlockingScheduler())


def run_scheduler_command(
    *,
    app_ref: str = "app.main:app",
    app_root: str | pathlib.Path = ".",
    scheduler: object | None = None,
) -> str:
    """Build *app_ref*, then run the in-process scheduler until stopped (the scheduler entrypoint).

    The scheduler-process entrypoint deferred from ADR 0048: building the app runs ``create_app``,
    so the live :class:`~terp.core.ScheduleCatalog` (and the :class:`~terp.core.JobCatalog` its
    jobs resolve against) is configured. It registers every declared schedule with an
    APScheduler-backed :class:`~terp.core.Scheduler` and starts it — each cron tick fires the
    schedule through the typed :func:`~terp.core.enqueue` chokepoint, so a scheduled job flows
    through the active :class:`~terp.core.JobQueue` (run it off-request with ``terp jobs worker``
    when the durable outbox is wired). ``start`` **blocks** until the process is stopped (SIGINT).
    *scheduler* is injectable for tests; the default wraps a blocking APScheduler and requires the
    ``terp-cap-scheduler-apscheduler`` capability.
    """
    root = str(pathlib.Path(app_root).resolve())
    if root not in sys.path:
        sys.path.insert(0, root)
    _load_app(app_ref)

    from terp.core.scheduling import active_schedule_catalog

    catalog = active_schedule_catalog()
    scheduler = scheduler if scheduler is not None else _default_scheduler()
    scheduler.register_all(catalog)
    names = ", ".join(catalog.names()) or "<none>"
    scheduler.start()  # blocks until the process is stopped (a long-running daemon)
    return f"scheduler stopped; {len(catalog.schedules)} schedule(s) registered: {names}"


__all__ = [
    "render_jobs",
    "run_job_command",
    "run_scheduler_command",
    "run_worker_command",
]
