"""Admin ``access`` (grants) router + the discoverable ``ModuleSpec``.

**Admin-only** (``Policy`` requires ``ADMIN``): managing who holds which
permission is itself a privileged action. Exposed as ``module`` so the kernel's
entry-point discovery mounts it at ``/api/v1/access`` with no composition-root
edit. Modules then gate their own actions with ``require_permission`` against the
grants administered here.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from terp.core import ModuleSpec, Page, PaginationDep, Policy, Roles, SessionDep

from terp.capabilities.access.schemas import GrantCreate, GrantRead
from terp.capabilities.access.service import AccessService

router = APIRouter(tags=["access"])
_service = AccessService()


@router.get("/grants", response_model=Page[GrantRead])
def list_grants(
    subject_id: uuid.UUID, session: SessionDep, pagination: PaginationDep
) -> Page[GrantRead]:
    rows, total = _service.list_for(
        session, subject_id, skip=pagination.skip, limit=pagination.limit
    )
    return Page[GrantRead].of(
        [GrantRead.model_validate(row) for row in rows], total, pagination
    )


@router.post("/grants", response_model=GrantRead, status_code=201)
def create_grant(payload: GrantCreate, session: SessionDep) -> GrantRead:
    return GrantRead.model_validate(
        _service.grant(session, payload.subject_id, payload.permission)
    )


@router.delete("/grants/{grant_id}", status_code=204)
def delete_grant(grant_id: uuid.UUID, session: SessionDep) -> None:
    _service.delete(session, grant_id)


module = ModuleSpec(
    name="access",
    router=router,
    policy=Policy(read_role=Roles.ADMIN, write_role=Roles.ADMIN),
)
