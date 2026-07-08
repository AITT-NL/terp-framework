"""terp.capabilities.scheduler_apscheduler — fire catalog schedules in-process via APScheduler.

The in-process :class:`~terp.core.Scheduler` adapter (the working design's §11): it triggers
each :class:`~terp.core.ScheduleDefinition` on its cron using APScheduler, with no domain
change. Wiring is composition-root / scheduler-process only::

    # a dedicated scheduler process (or a single-instance web process)
    scheduler = ApschedulerScheduler(session_factory=lambda: WriteGuardedSession(get_engine()))
    scheduler.register_all(active_schedule_catalog())   # after create_app configured it
    scheduler.start()                                   # then block the process

Each tick opens a session and fires the schedule through
:func:`~terp.core.trigger_schedule` — i.e. it **enqueues** the schedule's job through the
typed chokepoint, so the job flows through the active :class:`~terp.core.JobQueue` (in-process
/ outbox / broker) and the context-binding runner: a scheduled job has no originating user, so
it runs as the configured system actor and its writes stay audited + stamped.

APScheduler runs **in one process** with no distributed lock, so for a multi-instance
deployment use an external scheduler / Celery beat (or a single leader) to avoid duplicate
ticks (the design's §17). It depends only on ``terp-core`` + ``apscheduler`` and imports the
engine solely behind the scheduler seam (``no_adhoc_background_runtime`` keeps it out of app
code).
"""

from __future__ import annotations

from terp.capabilities.scheduler_apscheduler.scheduler import ApschedulerScheduler

__all__ = ["ApschedulerScheduler"]
