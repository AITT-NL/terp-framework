from terp.core.scheduling import ScheduleDefinition as Schedule

from control_plane.jobs import REMINDER

DAILY = Schedule(name="reminders.daily", job=REMINDER, cron="0 8 * * *")
