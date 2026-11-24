from terp.core import JobDefinition, ScheduleCatalog, ScheduleDefinition

SNAPSHOT = JobDefinition("notices.snapshot")

SCHEDULES = ScheduleCatalog(
    schedules=(ScheduleDefinition("notices.snapshot.hourly", SNAPSHOT, "0 * * * *"),)
)
