"""The schedule catalog: the one cron this app runs, declared once.

``terp jobs scheduler`` registers every schedule here with APScheduler and, on each
tick, enqueues the schedule's job through the typed chokepoint, so the tick is a row in
the outbox like any other job and ``terp jobs worker`` runs it. The scheduler serves no
traffic and is kept out of readiness: a scheduler that has stopped delays the next
snapshot, and turns nothing that serves a request red. Its own health is the heartbeat its
container is checked on (ADR 0191).

The hour a deploy stops the scheduler across is not lost: the app records every settled
slot in the outbox's ``DatabaseScheduleLedger`` (``app/main.py``), and the restarted
scheduler applies the declared misfire policy to the slot it missed.
"""

from __future__ import annotations

from terp.core import Misfire, ScheduleCatalog, ScheduleDefinition

from app.modules.notices.jobs import SNAPSHOT_TAKE

#: On the hour. A snapshot an hour is often enough to see the job run in a workbench left
#: open, and rare enough that the upstream never notices it. A snapshot taken late is still
#: a snapshot, so the hour missed during a deploy is taken once when the scheduler is back,
#: and the hours of a longer gap are folded into that one.
SNAPSHOT_HOURLY = ScheduleDefinition(
    name="notices.snapshot.hourly",
    job=SNAPSHOT_TAKE,
    cron="0 * * * *",
    misfire=Misfire.RUN_ONCE,
)

schedule_catalog = ScheduleCatalog((SNAPSHOT_HOURLY,))

__all__ = ["SNAPSHOT_HOURLY", "schedule_catalog"]
