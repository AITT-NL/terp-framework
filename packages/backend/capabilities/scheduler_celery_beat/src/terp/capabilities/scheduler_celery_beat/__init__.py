"""terp.capabilities.scheduler_celery_beat — drive catalog schedules from Celery beat.

The Celery-beat :class:`~terp.core.Scheduler` adapter (the working design's §11), for a
deployment already running the Celery stack. Wiring is composition-root only::

    scheduler = CeleryBeatScheduler(celery_app, session_factory=lambda: Session(get_engine()))
    scheduler.register_all(active_schedule_catalog())   # after create_app configured it
    scheduler.install()                                 # -> celery_app.conf.beat_schedule
    # then run:  celery -A your.celery_app beat   (plus a worker to run the enqueued jobs)

For each :class:`~terp.core.ScheduleDefinition` it registers a small **tick task** on the
Celery app and a ``beat_schedule`` entry that runs that task on the schedule's cron. When beat
fires the tick (on a worker), the tick opens a session and calls
:func:`~terp.core.trigger_schedule` — i.e. it **enqueues** the schedule's job through the typed
chokepoint and the active :class:`~terp.core.JobQueue`. Routing through a tick task (rather than
sending a fixed message) keeps the schedule's ``payload_factory`` dynamic per fire and the
no-drift ``enqueue`` validation in force.

It depends only on ``terp-core`` + ``celery`` and imports the engine solely behind the
scheduler seam (``no_adhoc_background_runtime`` keeps it out of app code).
"""

from __future__ import annotations

from terp.capabilities.scheduler_celery_beat.scheduler import CeleryBeatScheduler

__all__ = ["CeleryBeatScheduler"]
