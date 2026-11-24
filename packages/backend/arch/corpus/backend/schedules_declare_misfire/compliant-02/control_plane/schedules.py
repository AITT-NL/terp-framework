from terp.core import Misfire
from terp.core import ScheduleDefinition as Schedule

from control_plane.jobs import REMINDER


def daily(name: str) -> Schedule:
    # A missed reminder is worth nothing late: the hour it was for has passed.
    return Schedule(name=name, job=REMINDER, cron="0 8 * * *", misfire=Misfire.SKIP)
