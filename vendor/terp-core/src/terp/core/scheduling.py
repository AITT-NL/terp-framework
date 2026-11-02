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
**system actor** and its writes stay audited + stamped, with no special-casing. That
actor is ``ControlPlane.job_system_actor_id``, and it is not optional in production:
declaring a schedule without one refuses the boot, because a nightly tick whose rows name
no actor is the one answer a provenance column must not give.

**A tick that fell due while no scheduler ran** (ADR 0191). A scheduler is a process, and a
deploy, a crash or a host restart stops it; a cron time that passed meanwhile left no trace,
so nothing could say it was missed. Two things change that:

* every :class:`ScheduleDefinition` **declares** what a missed tick becomes, its
  :class:`Misfire` policy, as a required keyword: :attr:`Misfire.RUN_ONCE` runs it once,
  late, as soon as a scheduler is back (every earlier tick of the same gap folded into that
  one run), and :attr:`Misfire.SKIP` records it as skipped and waits for the next cron time.
  A default would read in the source exactly like a choice, which is why there is none;
* a :class:`ScheduleLedger` holds each schedule's **last settled slot**: the cron time it
  last fired, ran late or skipped, or the moment it was first seen. An adapter settles
  every tick through :func:`settle_schedule`, at start and on each cron time alike, so a
  scheduler that comes back across a cron time finds the slot the ledger has not settled
  and applies the policy to it. :class:`InMemoryScheduleLedger` is the default and forgets
  on restart; the durable one is the outbox capability's ``DatabaseScheduleLedger``, whose
  record commits in the same transaction as the outbox row the tick enqueues, and
  ``create_app(require_durable_schedules=True)`` refuses anything else.

Two-layer enforcement (ADR 0006), mirroring the jobs catalog: ``create_app`` boot-validates
every :class:`ScheduleDefinition` in the control plane's :class:`ScheduleCatalog` against the
:class:`~terp.core.JobCatalog` (a schedule enqueuing an undeclared job fails the boot), and a
schedule is always a typed catalog constant — there is no module-authored schedule string to
police with an AST rule, so (like the throttle store, ADR 0036) the build-time half is the
boot check + the kernel test, not a module-policing rule.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Final

from sqlmodel import Session

from terp.core.jobs import JobCatalog, JobDefinition, enqueue
from terp.core.runtime import register_runtime_seam
from terp.core.schedule_ledger import (
    BASELINE,
    FIRED,
    LATE,
    SKIPPED,
    InMemoryScheduleLedger,
    ScheduleLedger,
    ScheduleRecord,
    is_durable_schedule_ledger,
    mark_durable_schedule_ledger,
)

_logger = logging.getLogger("terp.core.scheduling")


def _is_dotted_token(value: str) -> bool:
    """True for dotted schedule names like ``sync.customers.pull`` (mirrors the jobs rule)."""
    if not value:
        return False
    return all(
        part and part.replace("_", "").replace("-", "").isalnum()
        for part in value.split(".")
    )


class Misfire(StrEnum):
    """What a schedule makes of a cron time no scheduler fired on time (ADR 0191).

    A slot is *on time* when it is settled within :data:`ON_TIME_SECONDS` of its cron time.
    One settled later is a misfire, almost always because no scheduler ran when it fell due:
    a deploy, a crash, a host restart.
    """

    #: Run it once, late, as soon as a scheduler is back. Every earlier slot of the same gap
    #: is folded into that one run, so a scheduler down for a day runs an hourly job once,
    #: not twenty-four times. The job must make sense late.
    RUN_ONCE = "run-once"
    #: Record it as skipped and wait for the next cron time: for work that is pointless
    #: late, such as a reminder for a meeting that has already started.
    SKIP = "skip"


#: A slot settled within this many seconds of its cron time is on time; later is a misfire.
#: A minute, the resolution of a five-field cron, so a tick an overloaded host started a few
#: seconds late is still the tick it was meant to be.
ON_TIME_SECONDS: Final[float] = 60.0


@dataclass(frozen=True)
class ScheduleDefinition:
    """A typed schedule: a namespaced *name*, the *job* to enqueue, a *cron* trigger and a
    declared *misfire* policy.

    The only thing a :class:`ScheduleCatalog` holds, so every schedule references a declared
    :class:`~terp.core.JobDefinition` catalog constant (never a bare string — the no-drift
    guarantee the jobs / event seams already enforce) and carries an explicit cron. The cron
    string is **opaque to the kernel** (layer 0 imports no cron parser); an engine adapter
    parses it. ``payload_factory`` produces the payload to enqueue each tick (``None`` →
    the job's empty/default payload), so a schedule whose payload depends on "now" stays
    dynamic — an adapter re-evaluates it each fire (both shipped adapters route every tick
    through this factory rather than freezing a payload at registration).

    *misfire* is required and keyword-only: what a tick that fell due while no scheduler ran
    should become is a property of the work, which only its author knows (ADR 0191).
    """

    name: str
    job: JobDefinition
    cron: str
    payload_factory: Callable[[], Any] | None = None
    misfire: Misfire = field(kw_only=True)

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
        if not isinstance(self.misfire, Misfire):
            raise TypeError(
                "ScheduleDefinition.misfire must be Misfire.RUN_ONCE or Misfire.SKIP, got "
                f"{self.misfire!r}: declare what a tick that fell due while no scheduler "
                "ran becomes (ADR 0191)"
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
    Both shipped adapters settle each tick through :func:`settle_schedule`, so a schedule's
    misfire policy holds whichever engine fires it.
    """

    @abstractmethod
    def register(self, schedule: ScheduleDefinition) -> None:
        """Register *schedule* with the concrete backend so it fires on its cron."""

    def register_all(self, catalog: ScheduleCatalog) -> None:
        """Register every schedule in *catalog* (the common adapter entry point)."""
        for schedule in catalog.schedules:
            self.register(schedule)


@dataclass(frozen=True)
class _SchedulesRuntime:
    catalog: ScheduleCatalog
    ledger: ScheduleLedger


def _default_runtime() -> _SchedulesRuntime:
    return _SchedulesRuntime(catalog=ScheduleCatalog.default(), ledger=InMemoryScheduleLedger())


_runtime: _SchedulesRuntime = _default_runtime()


def active_schedule_catalog() -> ScheduleCatalog:
    """The schedule catalog the runtime currently holds (set by ``create_app``)."""
    return _runtime.catalog


def active_schedule_ledger() -> ScheduleLedger:
    """The schedule ledger the runtime currently holds (set by ``create_app``)."""
    return _runtime.ledger


def configure_schedules(
    catalog: ScheduleCatalog, *, ledger: ScheduleLedger | None = None
) -> None:
    """Install the active schedule *catalog* and *ledger* (called by ``create_app``).

    Mirrors :func:`~terp.core.configure_jobs`: a scheduler process / the ``terp jobs
    schedule`` CLI reads the active catalog after building the app, so what it triggers
    always matches what the app declares. ``ledger=None`` installs a fresh
    :class:`InMemoryScheduleLedger`.
    """
    global _runtime
    _runtime = _SchedulesRuntime(
        catalog=catalog, ledger=ledger if ledger is not None else InMemoryScheduleLedger()
    )


def reset_schedules_runtime() -> None:
    """Restore the empty catalog and a fresh in-memory ledger (the per-app / test baseline)."""
    global _runtime
    _runtime = _default_runtime()


def _capture_schedules_runtime() -> _SchedulesRuntime:
    """Snapshot the installed catalog and ledger (the runtime-seam capture hook)."""
    return _runtime


def _restore_schedules_runtime(state: _SchedulesRuntime) -> None:
    """Put back a :func:`_capture_schedules_runtime` snapshot (the runtime-seam restore hook)."""
    global _runtime
    _runtime = state


register_runtime_seam(
    "schedules",
    capture=_capture_schedules_runtime,
    restore=_restore_schedules_runtime,
    reset=reset_schedules_runtime,
)


def trigger_schedule(session: Session, schedule: ScheduleDefinition) -> str:
    """Fire *schedule* once: build its payload and enqueue its job; return the job id.

    The producer-side helper the external-trigger CLI calls, and the half of
    :func:`settle_schedule` that enqueues. It goes through the typed :func:`~terp.core.enqueue`
    chokepoint, so the job flows through the active :class:`~terp.core.JobQueue` (in-process
    / outbox / broker) and the context-binding runner — with no originating user, the
    configured system actor stands in, so the job's writes stay audited + stamped.
    ``payload_factory`` is called per tick (``None`` → the job's empty/default payload), so a
    "now"-dependent payload stays fresh. It records nothing in a ledger.
    """
    payload = schedule.payload_factory() if schedule.payload_factory is not None else None
    return enqueue(session, job=schedule.job, payload=payload)


#: An adapter's cron, asked one question: the latest of its cron times in ``(after, until]``,
#: or ``None`` when there is none. The kernel parses no cron; the engine that does answers.
SlotFinder = Callable[[datetime, datetime], datetime | None]


@dataclass(frozen=True)
class Settled:
    """What :func:`settle_schedule` did: the outcome it recorded, for which slot, and the job.

    *outcome* is ``None`` when nothing was owed (the latest slot is already settled) or
    another scheduler settled it first; *job_id* is set when a job was enqueued.
    """

    schedule: str
    outcome: str | None = None
    slot: datetime | None = None
    job_id: str | None = None


def _utc(moment: datetime) -> datetime:
    """*moment* as an aware UTC value; a naive one is taken to be UTC already."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


def settle_schedule(
    session: Session,
    schedule: ScheduleDefinition,
    *,
    latest_slot: SlotFinder,
    now: datetime | None = None,
    ledger: ScheduleLedger | None = None,
) -> Settled:
    """Settle *schedule*'s latest cron time up to *now*, applying its misfire policy.

    The one decision every adapter makes, at start and on each cron time alike, on a session
    of the adapter's own. With the ledger's last slot ``L`` (or, for a schedule the ledger has
    never held, a minute before *now*), *latest_slot* names the latest cron time ``S`` in
    ``(L, now]``:

    * there is none: nothing is owed. A schedule the ledger has never held is recorded at
      *now* as its :data:`BASELINE`, so a later restart knows where its knowledge starts;
    * ``S`` is within :data:`ON_TIME_SECONDS` of *now*: its job is enqueued, :data:`FIRED`;
    * ``S`` is older: a misfire. :attr:`Misfire.RUN_ONCE` enqueues the job once,
      :data:`LATE`; :attr:`Misfire.SKIP` records :data:`SKIPPED` and enqueues nothing.

    Every slot between ``L`` and ``S`` is folded into ``S``: one run, or one skip. The ledger
    enqueues the job and moves its record as one unit (:meth:`ScheduleLedger.settle`): on the
    outbox queue and the database ledger that is one transaction, so a crash leaves both or
    neither. A record another scheduler moved first is never overwritten, and what was staged
    is rolled back. A broker queue publishes before the record commits, so delivery stays at
    least once and a scheduled job must tolerate running twice.
    """
    ledger = ledger if ledger is not None else active_schedule_ledger()
    moment = _utc(now if now is not None else datetime.now(UTC))
    record = ledger.last(session, schedule.name)
    after = record.slot if record is not None else moment - timedelta(seconds=ON_TIME_SECONDS)
    found = latest_slot(after, moment)
    if found is None:
        if record is not None:
            return Settled(schedule.name)
        return _settle(session, schedule, ledger, record, slot=moment, outcome=BASELINE)
    slot = _utc(found)
    if (moment - slot).total_seconds() <= ON_TIME_SECONDS:
        outcome = FIRED
    elif schedule.misfire is Misfire.RUN_ONCE:
        outcome = LATE
    else:
        outcome = SKIPPED
    return _settle(session, schedule, ledger, record, slot=slot, outcome=outcome)


def _settle(
    session: Session,
    schedule: ScheduleDefinition,
    ledger: ScheduleLedger,
    record: ScheduleRecord | None,
    *,
    slot: datetime,
    outcome: str,
) -> Settled:
    """Hand the decision to the ledger, which enqueues and records as one unit."""
    runs = outcome in (FIRED, LATE)
    moved, job_id = ledger.settle(
        session,
        schedule.name,
        expected=record,
        slot=slot,
        outcome=outcome,
        enqueue=(lambda: trigger_schedule(session, schedule)) if runs else None,
    )
    if not moved:
        _logger.warning(
            "schedule %r: the slot at %s was settled by another scheduler first, so this "
            "one recorded nothing%s",
            schedule.name,
            slot.isoformat(),
            "; its job had already left on a queue outside the transaction"
            if job_id is not None
            else "",
        )
        return Settled(schedule.name)
    if outcome == LATE:
        _logger.warning(
            "schedule %r: the tick due at %s ran late, once (misfire policy run-once)",
            schedule.name,
            slot.isoformat(),
        )
    elif outcome == SKIPPED:
        _logger.warning(
            "schedule %r: the tick due at %s was skipped (misfire policy skip); the next "
            "cron time runs as usual",
            schedule.name,
            slot.isoformat(),
        )
    return Settled(schedule.name, outcome=outcome, slot=slot, job_id=job_id)


__all__ = [
    "BASELINE",
    "FIRED",
    "LATE",
    "ON_TIME_SECONDS",
    "SKIPPED",
    "InMemoryScheduleLedger",
    "Misfire",
    "ScheduleCatalog",
    "ScheduleDefinition",
    "ScheduleLedger",
    "ScheduleRecord",
    "Scheduler",
    "Settled",
    "SlotFinder",
    "active_schedule_catalog",
    "active_schedule_ledger",
    "configure_schedules",
    "is_durable_schedule_ledger",
    "mark_durable_schedule_ledger",
    "reset_schedules_runtime",
    "settle_schedule",
    "trigger_schedule",
]
