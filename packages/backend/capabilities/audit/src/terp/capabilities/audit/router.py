"""Admin (read-only) audit-log router + the discoverable ``ModuleSpec``.

**Admin-only** (``Policy`` requires ``ADMIN``): the audit trail is privileged —
it records who did what across the whole app. Exposed as ``module`` so the
kernel's entry-point discovery mounts it at ``/api/v1/audit`` with no
composition-root edit. The log has no write surface here: rows are appended by the
sink inside each mutation's transaction, never through the API.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from terp.core import (
    ADMIN,
    ModuleAccess,
    ModuleSpec,
    Page,
    PaginationDep,
    Policy,
    SessionDep,
    operation,
)

from terp.capabilities.audit.operations import AUDIT_LIST_EVENTS, AUDIT_READ_ACTIVITY
from terp.capabilities.audit.schemas import AuditActivityRead, AuditEventRead
from terp.capabilities.audit.service import (
    ACTIVITY_MAX_DAYS,
    audit_activity,
    list_audit_events,
    resolve_time_zone,
)

router = APIRouter(tags=["audit"])


@router.get("/", response_model=Page[AuditEventRead])
@operation(AUDIT_LIST_EVENTS)
def list_events(
    session: SessionDep,
    pagination: PaginationDep,
    target_type: str | None = Query(
        None,
        max_length=128,
        description="Only events about records of this type -- the model's name, e.g. 'User'.",
    ),
    target_id: str | None = Query(
        None,
        max_length=128,
        description="Only events about the record with this id.",
    ),
) -> Page[AuditEventRead]:
    rows, total = list_audit_events(
        session, pagination=pagination, target_type=target_type, target_id=target_id
    )
    return Page[AuditEventRead].of(
        [AuditEventRead.model_validate(row) for row in rows], total, pagination
    )


@router.get("/activity", response_model=AuditActivityRead)
@operation(AUDIT_READ_ACTIVITY)
def read_activity(
    session: SessionDep,
    days: int = Query(
        30,
        ge=1,
        le=ACTIVITY_MAX_DAYS,
        description="How many calendar days to count, ending today; the days before are counted too.",
    ),
    time_zone: str = Query(
        "UTC",
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z][A-Za-z0-9_+-]*(/[A-Za-z0-9_+-]+)*$",
        description="The IANA time zone whose calendar days are counted, e.g. 'Europe/Amsterdam'.",
    ),
) -> AuditActivityRead:
    return audit_activity(session, days=days, zone=resolve_time_zone(time_zone))


module = ModuleSpec(
    name="audit",
    router=router,
    access=ModuleAccess.platform_only(
        reason="the audit log is the record every other module is answerable to, so it is never one module's to grant",
    ),
    policy=Policy(read=ADMIN, write=ADMIN),
)


__all__ = ["module", "router"]
