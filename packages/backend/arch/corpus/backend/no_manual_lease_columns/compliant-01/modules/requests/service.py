from terp.core import (
    AuditAction,
    BaseService,
    LeaseResource,
    hold_lease,
    register_lease_reaper,
)

from app.modules.requests.models import RunRequest
from app.modules.requests.schemas import RunRequestCreate, RunRequestUpdate

CLAIMED = "claimed"
QUEUED = "queued"


class RunRequestService(BaseService[RunRequest, RunRequestCreate, RunRequestUpdate]):
    model = RunRequest

    def __init__(self, holder: str) -> None:
        self._holder = holder

    def _after_write(self, session, entity, action):
        """Take the lease inside the write that claims the row, so the two agree.

        A resource somebody else holds raises here, before the write commits, so the row
        never reaches ``claimed`` at all — there is no compensating update to forget.
        """
        if entity.status == CLAIMED:
            hold_lease(
                session,
                LeaseResource.for_row(entity),
                holder=self._holder,
                ttl_seconds=60,
            )


def requeue_stale_request(session, lease) -> None:
    """The recovery an expired lease triggers: put the abandoned row back in the queue."""
    service = RunRequestService(holder="reaper")
    row = service.get(session, lease.resource.key)
    service.update(session, row.id, RunRequestUpdate(status=QUEUED, version=row.version))


register_lease_reaper("run_request", requeue_stale_request)
