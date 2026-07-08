"""Admin user-management router + the discoverable ``ModuleSpec``.

Admin-only (``Policy`` requires ``ADMIN`` for both read and write). Mounted at
``/api/v1/users`` purely via entry-point discovery — it owns the
user-administration surface over the identity store: list / get / provision /
edit / deactivate / reactivate / reset password. Deactivation is preferred over
deletion, so a user is never hard-removed here.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query

from terp.core import (
    ModuleSpec,
    Page,
    PaginationDep,
    Policy,
    Principal,
    Roles,
    SessionDep,
    get_principal,
)

from terp.capabilities.identity import RefreshTokenService
from terp.capabilities.users.schemas import (
    UserAdminUpdate,
    UserPasswordReset,
    UserProvision,
    UserRead,
)
from terp.capabilities.users.service import UsersService

router = APIRouter(tags=["users"])
# Admin security actions (deactivate / demote / reset-password) also revoke the target's
# refresh-token families (ADR 0054), so a reset after a compromise kills the refresh cookie
# too — not just the short-lived access token. For an app that issues no refresh tokens this
# is a harmless no-op (the family query returns nothing).
_service = UsersService(refresh_revoker=RefreshTokenService().revoke_all_for_user)


@router.get("/", response_model=Page[UserRead])
def list_users(
    session: SessionDep,
    pagination: PaginationDep,
    email: str | None = Query(
        None,
        max_length=254,
        description="Filter to users whose email contains this text (case-insensitive).",
    ),
) -> Page[UserRead]:
    if email:
        rows, total = _service.list_matching(
            session, email=email, skip=pagination.skip, limit=pagination.limit
        )
    else:
        rows, total = _service.list(
            session, skip=pagination.skip, limit=pagination.limit
        )
    return Page[UserRead].of(
        [UserRead.model_validate(row) for row in rows], total, pagination
    )


@router.post("/", response_model=UserRead, status_code=201)
def provision_user(payload: UserProvision, session: SessionDep) -> UserRead:
    return UserRead.model_validate(_service.create(session, payload))


@router.get("/{user_id}", response_model=UserRead)
def get_user(user_id: uuid.UUID, session: SessionDep) -> UserRead:
    return UserRead.model_validate(_service.get(session, user_id))


@router.patch("/{user_id}", response_model=UserRead)
def update_user(
    user_id: uuid.UUID,
    payload: UserAdminUpdate,
    session: SessionDep,
    principal: Principal | None = Depends(get_principal),
) -> UserRead:
    return UserRead.model_validate(
        _service.update(
            session,
            user_id,
            payload,
            actor_id=principal.id if principal is not None else None,
        )
    )


@router.post("/{user_id}/deactivate", response_model=UserRead)
def deactivate_user(
    user_id: uuid.UUID,
    session: SessionDep,
    principal: Principal | None = Depends(get_principal),
) -> UserRead:
    return UserRead.model_validate(
        _service.set_active(
            session,
            user_id,
            active=False,
            actor_id=principal.id if principal is not None else None,
        )
    )


@router.post("/{user_id}/reactivate", response_model=UserRead)
def reactivate_user(user_id: uuid.UUID, session: SessionDep) -> UserRead:
    return UserRead.model_validate(_service.set_active(session, user_id, active=True))


@router.post("/{user_id}/reset-password", response_model=UserRead)
def reset_user_password(
    user_id: uuid.UUID, payload: UserPasswordReset, session: SessionDep
) -> UserRead:
    return UserRead.model_validate(
        _service.reset_password(session, user_id, payload.password)
    )


module = ModuleSpec(
    name="users",
    router=router,
    policy=Policy(read_role=Roles.ADMIN, write_role=Roles.ADMIN),
)
