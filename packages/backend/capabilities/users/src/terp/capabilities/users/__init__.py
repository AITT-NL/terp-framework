"""terp.capabilities.users — admin user management over the identity store.

Provides a :class:`UsersService` and a **self-registering** admin ``users`` router
(list / get / provision / edit / deactivate / reactivate / reset password). The
kernel discovers ``module`` via the ``terp.capabilities`` entry point and mounts
it at ``/api/v1/users`` with no composition-root edit.

The persisted ``User`` (and ``authenticate``) live in ``terp-cap-identity``; this
capability is the **administration surface** over that store, so there is a single
user table shared with the login path. Every write is audited (it routes through
the ``BaseService`` chokepoint) and passwords are hashed via ``terp-cap-auth``.
"""

from __future__ import annotations

from terp.capabilities.users.router import module, router
from terp.capabilities.users.schemas import (
    UserAdminUpdate,
    UserPasswordReset,
    UserProvision,
    UserRead,
)
from terp.capabilities.users.service import UsersService

__all__ = [
    "UserAdminUpdate",
    "UserPasswordReset",
    "UserProvision",
    "UserRead",
    "UsersService",
    "module",
    "router",
]
