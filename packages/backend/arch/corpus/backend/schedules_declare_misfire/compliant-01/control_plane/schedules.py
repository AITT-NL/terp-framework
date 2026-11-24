from terp.core import JobDefinition, Misfire, ScheduleCatalog, ScheduleDefinition

SNAPSHOT = JobDefinition("notices.snapshot")

SCHEDULES = ScheduleCatalog(
    schedules=(
        ScheduleDefinition(
            "notices.snapshot.hourly", SNAPSHOT, "0 * * * *", misfire=Misfire.RUN_ONCE
        ),
    )
)
