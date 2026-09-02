"""Admin ``access`` (grants) router + the discoverable ``ModuleSpec``.

**Admin-only** (``Policy`` requires ``ADMIN``): managing who holds which
permission is itself a privileged action. Exposed as ``module`` so the kernel's
entry-point discovery mounts it at ``/api/v1/access`` with no composition-root
edit. Modules then gate their own actions with ``require_permission`` against the
grants administered here.

A grant names a permission the app **declares** (see :func:`_refuse_undeclared`), the
same check ``terp grant add`` has made since ADR 0089. Revocation deliberately makes no
such check: it is by grant id here, and a permission the app has since stopped declaring
is exactly the stale grant that most needs removing.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request

from terp.core import (
    ErrorDetail,
    ModuleSpec,
    Page,
    PaginationDep,
    Policy,
    Roles,
    SessionDep,
    ValidationFailedError,
    operation,
)

from terp.capabilities.access.operations import (
    ACCESS_CREATE_GRANT,
    ACCESS_DELETE_GRANT,
    ACCESS_LIST_GRANTS,
)
from terp.capabilities.access.schemas import GrantCreate, GrantRead
from terp.capabilities.access.service import AccessService

router = APIRouter(tags=["access"])
_service = AccessService()


def _refuse_undeclared(request: Request, permission: str) -> None:
    """Refuse *permission* unless the app declares it, and say what it does declare.

    ``terp grant add`` has validated against the app's own control plane since ADR 0089,
    for a reason that applies just as much here: a grant of a string the app never checks
    is not a lenient grant, it is a silent no-op, and whoever wrote it will believe the
    subject is authorized until the moment it is not. The HTTP path skipped the check, so
    the two write paths disagreed about the same table — the CLI refused a typo and the
    endpoint stored it.

    The catalog comes back in ``details`` rather than only in the prose, which is the one
    thing this can do that the command cannot: the caller is a permission editor, and a
    machine-readable list of the valid choices is what lets it offer them instead of
    asking someone to retype the name.

    Fails closed when the app exposes no control plane, exactly as the command does. Every
    real mount has one — ``create_app`` records it on ``app.state`` — so the only caller
    that can see this is a hand-composed app, and guessing on its behalf is the one
    outcome that could store an unenforceable grant.
    """
    plane = getattr(request.app.state, "terp_control_plane", None)
    if plane is None:
        raise ValidationFailedError(
            "this app exposes no control plane, so the permission cannot be checked "
            "against what it declares; grants are refused rather than stored unverified",
            details=(ErrorDetail(code="no_control_plane", loc="permission"),),
        )
    catalog = {p.name: p.min_role.name for p in plane.permissions.permissions}
    if permission in catalog:
        return
    raise ValidationFailedError(
        f"this app does not declare a permission named {permission!r}. A grant of a "
        "permission nothing checks is a silent no-op, so it is refused rather than "
        "stored; the permissions this app does declare are listed in the details.",
        details=(
            ErrorDetail(
                code="undeclared_permission", loc="permission", msg=permission
            ),
            *(
                ErrorDetail(
                    code="declared_permission",
                    loc=name,
                    msg=f"needs role {min_role} or higher",
                )
                for name, min_role in sorted(catalog.items())
            ),
        ),
    )


@router.get("/grants", response_model=Page[GrantRead])
@operation(ACCESS_LIST_GRANTS)
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
@operation(ACCESS_CREATE_GRANT)
def create_grant(
    payload: GrantCreate, request: Request, session: SessionDep
) -> GrantRead:
    _refuse_undeclared(request, payload.permission)
    return GrantRead.model_validate(
        _service.grant(session, payload.subject_id, payload.permission)
    )


@router.delete("/grants/{grant_id}", status_code=204)
@operation(ACCESS_DELETE_GRANT)
def delete_grant(grant_id: uuid.UUID, session: SessionDep) -> None:
    _service.delete(session, grant_id)


module = ModuleSpec(
    name="access",
    router=router,
    policy=Policy(read_role=Roles.ADMIN, write_role=Roles.ADMIN),
)
