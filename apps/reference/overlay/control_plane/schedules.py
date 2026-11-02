"""The schedule catalog: the one cron this app runs, declared once.

``terp jobs scheduler`` registers every schedule here with APScheduler and, on each
tick, enqueues the schedule's job through the typed chokepoint, so the tick is a row in
the outbox like any other job and ``terp jobs worker`` runs it. The scheduler serves no
traffic and is kept out of readiness: a scheduler that has stopped delays the next
snapshot, and turns nothing that serves a request red.
"""

from __future__ import annotations

from terp.core import ScheduleCatalog, ScheduleDefinition

from app.modules.notices.jobs import SNAPSHOT_TAKE

#: On the hour. A snapshot an hour is often enough to see the job run in a workbench left
#: open, and rare enough that the upstream never notices it.
SNAPSHOT_HOURLY = ScheduleDefinition(
    name="notices.snapshot.hourly",
    job=SNAPSHOT_TAKE,
    cron="0 * * * *",
)

schedule_catalog = ScheduleCatalog((SNAPSHOT_HOURLY,))

__all__ = ["SNAPSHOT_HOURLY", "schedule_catalog"]
