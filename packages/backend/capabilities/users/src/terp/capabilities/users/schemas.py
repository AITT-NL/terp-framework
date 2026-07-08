"""Users capability DTOs — admin management over the identity ``User`` store.

The read shape reuses identity's ``UserRead`` (which never exposes
``hashed_password``); this module adds the admin write DTOs. ``UserAdminUpdate``
requires the optimistic-concurrency ``version`` like every other update schema.

The ``password`` ``max_length`` is the DoS cap; *strength* is enforced one layer in,
at the ``UsersService`` write chokepoint (ADR 0032), so a rejection is the uniform
typed ``WeakPasswordError`` envelope rather than a raw pydantic 422.
"""

from __future__ import annotations

from sqlmodel import Field

from terp.core import BaseSchema, BaseUpdateSchema, Roles

from terp.capabilities.identity import UserRead

__all__ = [
    "UserAdminUpdate",
    "UserPasswordReset",
    "UserProvision",
    "UserRead",
]


class UserProvision(BaseSchema):
    """Admin-provisions a new user with an initial password and a role *rank*.

    ``role`` is an integer rank resolved against the app's ``PermissionModel`` at
    login (ADR 0022), so an admin can provision any role the app's ladder defines —
    not only the default three tiers; an unmodeled rank simply fails closed at that
    user's next login. The default is the viewer rank.
    """

    email: str = Field(max_length=320)
    password: str = Field(max_length=256)
    role: int = Field(default=int(Roles.VIEWER), ge=0)


class UserAdminUpdate(BaseUpdateSchema):
    """Admin edits a user's email / role rank (OCC ``version`` required).

    Activation state is changed through the dedicated ``deactivate`` /
    ``reactivate`` actions, not this generic patch.
    """

    email: str | None = Field(default=None, max_length=320)
    role: int | None = Field(default=None, ge=0)


class UserPasswordReset(BaseSchema):
    """Admin sets a new password for a user."""

    password: str = Field(max_length=256)
