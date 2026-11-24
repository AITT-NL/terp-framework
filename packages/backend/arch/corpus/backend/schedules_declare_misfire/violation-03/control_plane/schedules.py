import terp.core as core

from control_plane.jobs import CLEANUP

NIGHTLY = core.ScheduleDefinition("cleanup.nightly", CLEANUP, "0 3 * * *", payload_factory=dict)
