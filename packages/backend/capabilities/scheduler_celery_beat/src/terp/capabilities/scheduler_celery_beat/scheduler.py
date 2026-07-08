"""The Celery-beat :class:`~terp.core.Scheduler` adapter: cron entries fire catalog jobs.

For each :class:`~terp.core.ScheduleDefinition`, :meth:`CeleryBeatScheduler.register` registers
a small **tick task** on the Celery app and a ``beat_schedule`` entry that runs that task on the
schedule's cron. When Celery beat fires the tick (on a worker), the tick opens a session and
calls :func:`~terp.core.trigger_schedule` — i.e. it **enqueues** the schedule's job through the
typed chokepoint and the active :class:`~terp.core.JobQueue`. Routing through a tick task (rather
than beat sending a fixed message) keeps the schedule's ``payload_factory`` **dynamic** per fire
and the no-drift ``enqueue`` validation in force.

The cron string is translated to a Celery ``crontab`` (a standard 5-field ``minute hour
day-of-month month day-of-week``), so a malformed cron fails at registration.

**Deployment.** The tick tasks are registered on the Celery app *in the calling process*, so
every Celery **worker** that may run them must be bootstrapped the same way — import the
composition root that builds the app (``create_app``, so the live ``JobCatalog`` / ``JobQueue``
are configured) and call :meth:`CeleryBeatScheduler.register_all` — otherwise beat publishes
``terp.schedule.*`` and a worker cannot resolve the task or its job. Run ``celery -A
your.celery_app beat`` for the timer and ``celery -A your.celery_app worker`` (bootstrapped
identically) for the ticks.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlmodel import Session

from terp.core import ScheduleDefinition, Scheduler, trigger_schedule

from celery import Celery  # arch-allow-no-adhoc-background-runtime: this capability IS the Celery-beat adapter — the one governed place the engine is imported, behind the scheduler seam
from celery.schedules import crontab  # arch-allow-no-adhoc-background-runtime: the cron parser the scheduler seam delegates to

_TASK_PREFIX = "terp.schedule."


def _to_crontab(cron: str) -> crontab:
    """Translate a standard 5-field cron string into a Celery ``crontab`` schedule.

    ``minute hour day-of-month month day-of-week`` — the portable subset every cron speaks.
    A cron with any other field count is rejected here (rather than firing on the wrong
    minute), so a bad schedule fails at registration.
    """
    fields = cron.split()
    if len(fields) != 5:
        raise ValueError(
            f"CeleryBeatScheduler needs a 5-field cron (minute hour day-of-month month "
            f"day-of-week), got {cron!r}"
        )
    minute, hour, day_of_month, month_of_year, day_of_week = fields
    return crontab(
        minute=minute,
        hour=hour,
        day_of_month=day_of_month,
        month_of_year=month_of_year,
        day_of_week=day_of_week,
    )


class CeleryBeatScheduler(Scheduler):
    """A :class:`~terp.core.Scheduler` that drives catalog schedules from Celery beat.

    Construct it with the Celery app and a *session_factory* for each tick's short-lived
    session (the tick only *enqueues*, so a plain session suffices). :meth:`register` /
    :meth:`register_all` register the tick tasks + build the ``beat_schedule``; :meth:`install`
    merges it onto the Celery app's config, after which ``celery -A your.celery_app beat`` fires
    them (and a worker runs the enqueued jobs).
    """

    def __init__(
        self,
        celery_app: Celery,
        session_factory: Callable[[], Session],
        *,
        task_prefix: str = _TASK_PREFIX,
    ) -> None:
        self._app = celery_app
        self._session_factory = session_factory
        self._task_prefix = task_prefix
        self._beat_schedule: dict[str, dict[str, Any]] = {}

    def register(self, schedule: ScheduleDefinition) -> None:
        """Register *schedule*'s tick task and a beat entry firing it on its cron."""
        task_name = f"{self._task_prefix}{schedule.name}"
        self._app.task(name=task_name)(self._make_tick(schedule))
        self._beat_schedule[schedule.name] = {
            "task": task_name,
            "schedule": _to_crontab(schedule.cron),
        }

    def _make_tick(self, schedule: ScheduleDefinition) -> Callable[[], str]:
        """Build the per-tick callable: open a session and fire the schedule (enqueue)."""
        session_factory = self._session_factory

        def _tick() -> str:
            with session_factory() as session:
                return trigger_schedule(session, schedule)

        return _tick

    @property
    def beat_schedule(self) -> dict[str, dict[str, Any]]:
        """The Celery ``beat_schedule`` built so far (a copy)."""
        return dict(self._beat_schedule)

    def install(self) -> None:
        """Merge the built ``beat_schedule`` onto the Celery app's config (then run beat)."""
        merged = dict(self._app.conf.beat_schedule or {})
        merged.update(self._beat_schedule)
        self._app.conf.beat_schedule = merged


__all__ = ["CeleryBeatScheduler"]
