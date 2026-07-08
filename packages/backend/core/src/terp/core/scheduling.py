"""The schedule catalog + scheduler seam: declare cron triggers as typed catalog constants.

This is the scheduling half of Terp's async design (the working design's §11): the small,
typed port a deployment uses to say "enqueue this **named, catalog-registered** job on this
cron", without naming a scheduler engine. It sits beside the jobs seam (ADR 0043) exactly as
that sits beside the event bus: a :class:`ScheduleDefinition` references a typed
:class:`~terp.core.JobDefinition` (never a bare string), a :class:`ScheduleCatalog` indexes
them and rejects duplicates, and a :class:`Scheduler` ABC is the one method an engine adapter
(APScheduler in-process, Celery beat, a k8s CronJob calling ``terp jobs schedule``) fills.

``terp.core`` is layer 0, so this module imports **no** scheduler engine (no ``apscheduler``
/ ``celery`` / ``croniter``): the cron string is opaque here and parsed by the adapter. The
safe default is the design's **external trigger** (§8) — ``terp jobs schedule <name>`` (or
``terp jobs run``) invoked by any cron / k8s CronJob / systemd timer / Azure timer — so a
scheduled job works today with zero scheduler infra. A schedule fires by *enqueuing* its job
through the typed :func:`~terp.core.enqueue` chokepoint (:func:`trigger_schedule`), so it
flows through the active :class:`~terp.core.JobQueue` (in-process / outbox / broker) and the
context-binding runner: a scheduled job has no originating user, so it runs as the configured
**system actor** and its writes stay audited + stamped, with no special-casing.

Two-layer enforcement (ADR 0006), mirroring the jobs catalog: ``create_app`` boot-validates
every :class:`ScheduleDefinition` in the control plane's :class:`ScheduleCatalog` against the
:class:`~terp.core.JobCatalog` (a schedule enqueuing an undeclared job fails the boot), and a
schedule is always a typed catalog constant — there is no module-authored schedule string to
police with an AST rule, so (like the throttle store, ADR 0036) the build-time half is the
boot check + the kernel test, not a module-policing rule.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlmodel import Session

from terp.core.jobs import JobCatalog, JobDefinition, enqueue


def _is_dotted_token(value: str) -> bool:
    """True for dotted schedule names like ``sync.customers.pull`` (mirrors the jobs rule)."""
    if not value:
        return False
    return all(
        part and part.replace("_", "").replace("-", "").isalnum()
        for part in value.split(".")
    )


@dataclass(frozen=True)
class ScheduleDefinition:
    """A typed schedule: a namespaced *name*, the *job* to enqueue, and a *cron* trigger.

    The only thing a :class:`ScheduleCatalog` holds, so every schedule references a declared
    :class:`~terp.core.JobDefinition` catalog constant (never a bare string — the no-drift
    guarantee the jobs / event seams already enforce) and carries an explicit cron. The cron
    string is **opaque to the kernel** (layer 0 imports no cron parser); an engine adapter
    parses it. ``payload_factory`` produces the payload to enqueue each tick (``None`` →
    the job's empty/default payload), so a schedule whose payload depends on "now" stays
    dynamic — an adapter re-evaluates it each fire (both shipped adapters route every tick
    through this factory rather than freezing a payload at registration).
    """

    name: str
    job: JobDefinition
    cron: str
    payload_factory: Callable[[], Any] | None = None

    def __post_init__(self) -> None:
        if not _is_dotted_token(self.name):
            raise ValueError(
                f"ScheduleDefinition.name must be a dotted token, got {self.name!r}"
            )
        if not isinstance(self.job, JobDefinition):
            raise TypeError(
                f"ScheduleDefinition.job must be a JobDefinition, got {self.job!r}"
            )
        if not self.cron or not self.cron.strip():
            raise ValueError(
                "ScheduleDefinition.cron must be a non-empty cron expression"
            )
        if self.payload_factory is not None and not callable(self.payload_factory):
            raise TypeError(
                f"ScheduleDefinition.payload_factory must be callable, got {self.payload_factory!r}"
            )


@dataclass(frozen=True)
class ScheduleCatalog:
    """The central registry of every :class:`ScheduleDefinition` an app triggers.

    Mirrors :class:`~terp.core.JobCatalog`: the default is **empty**, names are unique, and a
    schedule's job is boot-validated against the job catalog (:meth:`missing_jobs`) so a
    schedule can never enqueue a job the app does not declare.
    """

    schedules: tuple[ScheduleDefinition, ...] = ()

    def __post_init__(self) -> None:
        schedules = tuple(self.schedules)
        by_name: dict[str, ScheduleDefinition] = {}
        for schedule in schedules:
            if schedule.name in by_name:
                raise ValueError(f"duplicate schedule declaration: {schedule.name!r}")
            by_name[schedule.name] = schedule
        object.__setattr__(self, "schedules", schedules)
        object.__setattr__(self, "_by_name", by_name)

    @classmethod
    def default(cls) -> ScheduleCatalog:
        """The compatibility catalog: empty — no schedules are declared."""
        return cls()

    def has_name(self, name: str) -> bool:
        """Return whether a schedule with *name* is registered."""
        return name in self._by_name

    def get(self, name: str) -> ScheduleDefinition | None:
        """Return the schedule registered for *name* (or ``None``)."""
        return self._by_name.get(name)

    def names(self) -> tuple[str, ...]:
        """The registered schedule names, in declaration order."""
        return tuple(schedule.name for schedule in self.schedules)

    def missing_jobs(self, job_catalog: JobCatalog) -> tuple[ScheduleDefinition, ...]:
        """Every schedule whose job is not the registered entry of *job_catalog* (boot drift).

        Matched by value (``JobCatalog.has_job``), so a schedule pointing at a same-name
        *shadow* job (different handler / schema) is reported too — the schedule catalog
        cannot drift in a job the catalog does not canonically declare.
        """
        return tuple(
            schedule
            for schedule in self.schedules
            if not job_catalog.has_job(schedule.job)
        )


class Scheduler(ABC):
    """A backend that triggers a :class:`ScheduleDefinition` on its cron (the engine seam).

    The one method an adapter implements (APScheduler in-process, Celery beat, …). The kernel
    never runs a scheduler — a scheduler is a separate process (like the outbox worker), so a
    deployment builds the app to configure the live :class:`ScheduleCatalog`, then a chosen
    adapter :meth:`register_all` + starts it. The safe default needs no adapter at all: an
    external cron invokes ``terp jobs schedule <name>``, which calls :func:`trigger_schedule`.
    """

    @abstractmethod
    def register(self, schedule: ScheduleDefinition) -> None:
        """Register *schedule* with the concrete backend so it fires on its cron."""

    def register_all(self, catalog: ScheduleCatalog) -> None:
        """Register every schedule in *catalog* (the common adapter entry point)."""
        for schedule in catalog.schedules:
            self.register(schedule)


_active_schedule_catalog: ScheduleCatalog = ScheduleCatalog.default()


def active_schedule_catalog() -> ScheduleCatalog:
    """The schedule catalog the runtime currently holds (set by ``create_app``)."""
    return _active_schedule_catalog


def configure_schedules(catalog: ScheduleCatalog) -> None:
    """Install the active schedule *catalog* (called by ``create_app``).

    Mirrors :func:`~terp.core.configure_jobs`: a scheduler process / the ``terp jobs
    schedule`` CLI reads the active catalog after building the app, so what it triggers
    always matches what the app declares.
    """
    global _active_schedule_catalog
    _active_schedule_catalog = catalog


def reset_schedules_runtime() -> None:
    """Restore the empty schedule catalog (the per-app / test baseline)."""
    global _active_schedule_catalog
    _active_schedule_catalog = ScheduleCatalog.default()


def trigger_schedule(session: Session, schedule: ScheduleDefinition) -> str:
    """Fire *schedule* once: build its payload and enqueue its job; return the job id.

    The producer-side helper an adapter's tick / the external-trigger CLI calls. It enqueues
    through the typed :func:`~terp.core.enqueue` chokepoint, so the job flows through the
    active :class:`~terp.core.JobQueue` (in-process / outbox / broker) and the context-binding
    runner — with no originating user, the configured system actor stands in, so the job's
    writes stay audited + stamped. ``payload_factory`` is called per tick (``None`` → the
    job's empty/default payload), so a "now"-dependent payload stays fresh.
    """
    payload = schedule.payload_factory() if schedule.payload_factory is not None else None
    return enqueue(session, job=schedule.job, payload=payload)


__all__ = [
    "ScheduleCatalog",
    "ScheduleDefinition",
    "Scheduler",
    "active_schedule_catalog",
    "configure_schedules",
    "reset_schedules_runtime",
    "trigger_schedule",
]
