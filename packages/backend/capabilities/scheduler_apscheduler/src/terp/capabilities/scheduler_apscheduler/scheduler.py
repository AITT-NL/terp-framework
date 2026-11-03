"""The APScheduler :class:`~terp.core.Scheduler` adapter: cron triggers fire catalog jobs.

:meth:`ApschedulerScheduler.register` adds a cron job to an APScheduler instance whose tick
opens a session and settles the schedule via :func:`~terp.core.settle_schedule`, which
enqueues the schedule's job through the typed chokepoint and the active
:class:`~terp.core.JobQueue` and records the slot in the active
:class:`~terp.core.ScheduleLedger`. The cron string is parsed by APScheduler's
:class:`~apscheduler.triggers.cron.CronTrigger`, so a malformed cron fails at registration
rather than silently never firing.

**A tick missed while no scheduler ran** (ADR 0191). :meth:`ApschedulerScheduler.start`
settles every registered schedule before the engine starts, so a scheduler that comes back
after a deploy finds the cron time it missed and applies the schedule's declared
:class:`~terp.core.Misfire` policy: run it once, late, or record it skipped. The engine is
told to run a late tick rather than drop it (``misfire_grace_time=None``, coalesced), so the
policy, not APScheduler's one-second grace, decides what a late tick becomes, whether the
scheduler was down or merely slow.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta, tzinfo

from sqlmodel import Session

from terp.core import (
    ScheduleDefinition,
    ScheduleLedger,
    Scheduler,
    Settled,
    settle_schedule,
)
from terp.core.scheduling import SlotFinder

from apscheduler.schedulers.background import BackgroundScheduler  # arch-allow-no-adhoc-background-runtime: this capability IS the APScheduler adapter — the one governed place the engine is imported, behind the scheduler seam
from apscheduler.triggers.cron import CronTrigger  # arch-allow-no-adhoc-background-runtime: the cron parser the scheduler seam delegates to
from apscheduler.triggers.interval import IntervalTrigger  # arch-allow-no-adhoc-background-runtime: the interval trigger the scheduler process's heartbeat runs on


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _slot_finder(trigger: CronTrigger) -> SlotFinder:
    """The latest fire time of *trigger* in ``(after, until]``, as the kernel asks for it."""

    def latest(after: datetime, until: datetime) -> datetime | None:
        found = None
        moment = trigger.get_next_fire_time(None, after + timedelta(microseconds=1))
        while moment is not None and moment <= until:
            found = moment
            moment = trigger.get_next_fire_time(moment, moment)
        return found

    return latest


class ApschedulerScheduler(Scheduler):
    """An in-process :class:`~terp.core.Scheduler` backed by APScheduler.

    Construct it with a *session_factory* for each tick's short-lived session and,
    optionally, an APScheduler instance to wrap (default a fresh ``BackgroundScheduler``; a
    dedicated scheduler process may pass a ``BlockingScheduler`` whose :meth:`start`
    blocks). *ledger* is the :class:`~terp.core.ScheduleLedger` each tick settles through
    (default: the one ``create_app`` installed, read at each tick); *timezone* is the zone
    a cron is read in (default: the host's, as APScheduler reads it); *clock* is injectable
    for tests. :meth:`register` / :meth:`register_all` add the cron jobs; :meth:`start`
    settles every schedule and starts the engine; :meth:`shutdown` stops it.
    """

    def __init__(
        self,
        session_factory: Callable[[], Session],
        *,
        scheduler: object | None = None,
        ledger: ScheduleLedger | None = None,
        timezone: tzinfo | None = None,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._scheduler = scheduler if scheduler is not None else BackgroundScheduler()
        self._ledger = ledger
        self._timezone = timezone
        self._clock = clock
        self._registered: list[tuple[ScheduleDefinition, SlotFinder]] = []

    def register(self, schedule: ScheduleDefinition) -> None:
        """Add *schedule* as a cron job that settles it through the jobs seam."""
        trigger = CronTrigger.from_crontab(schedule.cron, timezone=self._timezone)
        finder = _slot_finder(trigger)
        self._scheduler.add_job(
            self._make_tick(schedule, finder),
            trigger=trigger,
            id=schedule.name,
            name=schedule.name,
            replace_existing=True,
            # A late tick is run, and the schedule's misfire policy decides what it
            # becomes; APScheduler's own grace would drop it after one second.
            misfire_grace_time=None,
            coalesce=True,
            max_instances=1,
        )
        self._registered.append((schedule, finder))

    def settle(self, schedule: ScheduleDefinition, finder: SlotFinder) -> Settled:
        """Settle *schedule* now, on a session of its own."""
        with self._session_factory() as session:
            return settle_schedule(
                session, schedule, latest_slot=finder, now=self._clock(), ledger=self._ledger
            )

    def catch_up(self) -> list[Settled]:
        """Settle every registered schedule now: the misfire policy for each missed tick."""
        return [self.settle(schedule, finder) for schedule, finder in self._registered]

    def _make_tick(self, schedule: ScheduleDefinition, finder: SlotFinder) -> Callable[[], None]:
        """Build the per-tick callback: settle the schedule (enqueue, and record the slot)."""

        def _tick() -> None:
            self.settle(schedule, finder)

        return _tick

    def every(self, seconds: float, callback: Callable[[], None]) -> None:
        """Run *callback* every *seconds* on the engine's own loop, and once at start.

        For ``terp jobs scheduler``'s heartbeat: a beat that runs only while the engine
        dispatches jobs is a liveness of the engine, not of the process.
        """
        self._scheduler.add_job(
            callback,
            trigger=IntervalTrigger(seconds=seconds),
            id="terp.scheduler.heartbeat",
            name="terp.scheduler.heartbeat",
            replace_existing=True,
            next_run_time=self._clock(),
            coalesce=True,
            max_instances=1,
        )

    def start(self) -> None:
        """Settle every registered schedule, then start the engine (blocking, for a process)."""
        self.catch_up()
        self._scheduler.start()

    def shutdown(self, *, wait: bool = True) -> None:
        """Stop the underlying APScheduler; *wait* lets the ticks in flight finish."""
        self._scheduler.shutdown(wait=wait)


__all__ = ["ApschedulerScheduler"]
