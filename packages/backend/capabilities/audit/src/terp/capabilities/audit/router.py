"""Admin (read-only) audit-log router + the discoverable ``ModuleSpec``.

**Admin-only** (``Policy`` requires ``ADMIN``): the audit trail is privileged —
it records who did what across the whole app. Exposed as ``module`` so the
kernel's entry-point discovery mounts it at ``/api/v1/audit`` with no
composition-root edit. The log has no write surface here: rows are appended by the
sink inside each mutation's transaction, never through the API.
"""

from __future__ import annotations

from fastapi import APIRouter

from terp.core import ADMIN, ModuleSpec, Page, PaginationDep, Policy, SessionDep

from terp.capabilities.audit.schemas import AuditEventRead
from terp.capabilities.audit.service import list_audit_events

router = APIRouter(tags=["audit"])


@router.get("/", response_model=Page[AuditEventRead])
def list_events(session: SessionDep, pagination: PaginationDep) -> Page[AuditEventRead]:
    rows, total = list_audit_events(session, pagination=pagination)
    return Page[AuditEventRead].of(
        [AuditEventRead.model_validate(row) for row in rows], total, pagination
    )


module = ModuleSpec(
    name="audit",
    router=router,
    policy=Policy(read=ADMIN, write=ADMIN),
)


__all__ = ["module", "router"]
