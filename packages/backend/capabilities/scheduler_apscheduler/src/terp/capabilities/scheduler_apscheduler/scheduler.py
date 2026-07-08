"""The APScheduler :class:`~terp.core.Scheduler` adapter: cron triggers fire catalog jobs.

:meth:`ApschedulerScheduler.register` adds a cron job to an APScheduler instance whose tick
opens a session and fires the schedule via :func:`~terp.core.trigger_schedule` (which enqueues
the schedule's job through the typed chokepoint and the active :class:`~terp.core.JobQueue`).
The cron string is parsed by APScheduler's :class:`~apscheduler.triggers.cron.CronTrigger`, so
a malformed cron fails at registration rather than silently never firing.
"""

from __future__ import annotations

from collections.abc import Callable

from sqlmodel import Session

from terp.core import ScheduleDefinition, Scheduler, trigger_schedule

from apscheduler.schedulers.background import BackgroundScheduler  # arch-allow-no-adhoc-background-runtime: this capability IS the APScheduler adapter — the one governed place the engine is imported, behind the scheduler seam
from apscheduler.triggers.cron import CronTrigger  # arch-allow-no-adhoc-background-runtime: the cron parser the scheduler seam delegates to


class ApschedulerScheduler(Scheduler):
    """An in-process :class:`~terp.core.Scheduler` backed by APScheduler.

    Construct it with a *session_factory* for each tick's short-lived session (the schedule
    only *enqueues*, so a plain session suffices) and, optionally, an APScheduler instance to
    wrap (default a fresh ``BackgroundScheduler``; a dedicated scheduler process may pass a
    ``BlockingScheduler`` whose :meth:`start` blocks). :meth:`register` / :meth:`register_all`
    add the cron jobs; :meth:`start` / :meth:`shutdown` drive the underlying engine.
    """

    def __init__(
        self,
        session_factory: Callable[[], Session],
        *,
        scheduler: object | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._scheduler = scheduler if scheduler is not None else BackgroundScheduler()

    def register(self, schedule: ScheduleDefinition) -> None:
        """Add *schedule* as a cron job that fires it through the jobs seam."""
        self._scheduler.add_job(
            self._make_tick(schedule),
            trigger=CronTrigger.from_crontab(schedule.cron),
            id=schedule.name,
            name=schedule.name,
            replace_existing=True,
        )

    def _make_tick(self, schedule: ScheduleDefinition) -> Callable[[], None]:
        """Build the per-tick callback: open a session and fire the schedule (enqueue)."""
        session_factory = self._session_factory

        def _tick() -> None:
            with session_factory() as session:
                trigger_schedule(session, schedule)

        return _tick

    def start(self) -> None:
        """Start the underlying APScheduler (background thread, or blocking for a worker)."""
        self._scheduler.start()

    def shutdown(self, *, wait: bool = True) -> None:
        """Stop the underlying APScheduler."""
        self._scheduler.shutdown(wait=wait)


__all__ = ["ApschedulerScheduler"]
