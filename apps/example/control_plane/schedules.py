"""Example-app schedule catalog: the one cron this app runs, declared once.

``terp jobs scheduler`` settles every schedule here when it starts and on each cron time,
enqueueing the schedule's job through the typed chokepoint, so a tick is an outbox row like
any other job and ``terp jobs worker`` runs it. The example's ``DatabaseScheduleLedger``
(``app/main.py``) records each settled slot in the same transaction as that row.
"""

from __future__ import annotations

from terp.core import Misfire, ScheduleCatalog, ScheduleDefinition

from app.probe import PROBE_RUN

#: Every minute, so a scheduler that has just started fires at once: the minute that began
#: less than a minute ago is on time. That is what lets the production smoke see a fire
#: without waiting for a cron time. A minute missed while no scheduler ran is run once when
#: one is back, and a longer gap is folded into that one run.
PROBE_MINUTELY = ScheduleDefinition(
    name="ops.probe.minutely",
    job=PROBE_RUN,
    cron="* * * * *",
    misfire=Misfire.RUN_ONCE,
)

schedule_catalog = ScheduleCatalog((PROBE_MINUTELY,))

__all__ = ["PROBE_MINUTELY", "schedule_catalog"]
