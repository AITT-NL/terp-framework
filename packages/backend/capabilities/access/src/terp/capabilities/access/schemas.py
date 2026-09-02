"""Access DTOs. Grants are immutable, so there is no public ``*Update`` surface.

The ``AccessModel*`` DTOs are the typed shape of ``GET /model``. They exist rather than a
loose mapping because the frontend contract is generated from this app's OpenAPI document
(ADR 0041), so the schema *is* the pane's type: an untyped payload would hand the surface
that renders a permission matrix nothing to check itself against, which is the whole reason
the matrix is being built on declarations in the first place.
"""

from __future__ import annotations

import datetime
import uuid

from sqlmodel import Field

from terp.core import BaseSchema, BaseUpdateSchema


class GrantCreate(BaseSchema):
    subject_id: uuid.UUID
    permission: str = Field(max_length=128)


class GrantUpdate(BaseUpdateSchema):
    """Grants are immutable (subject + permission) — nothing is updatable.

    Present only to satisfy ``BaseService``'s ``UpdateT`` type parameter; the
    admin router never exposes an update route.
    """


class GrantRead(BaseSchema):
    id: uuid.UUID
    subject_id: uuid.UUID
    permission: str
    version: int
    created_at: datetime.datetime
    updated_at: datetime.datetime


class ModuleRoleCreate(BaseSchema):
    subject_id: uuid.UUID
    module: str = Field(max_length=64)
    role_rank: int


class ModuleRoleUpdate(BaseUpdateSchema):
    """A module role's rank *is* editable, unlike a grant.

    A subject moving from editor to admin inside one module is the same fact with a new
    value, not a second fact — the unique constraint on ``(subject_id, module)`` says so —
    so this carries the one field that can change.
    """

    role_rank: int | None = None


class ModuleRoleRead(BaseSchema):
    id: uuid.UUID
    subject_id: uuid.UUID
    module: str
    role_rank: int
    version: int
    created_at: datetime.datetime
    updated_at: datetime.datetime


class AccessRoleRead(BaseSchema):
    """One rung of the app's declared ladder."""

    name: str
    rank: int


class AccessPermissionRead(BaseSchema):
    """One declared permission: its name, its rank floor, and what holding it buys."""

    name: str
    min_role: str
    #: ``None`` where the app has not written one. Distinguished from a missing key on
    #: purpose — a pane must be able to tell "no label declared" from "this payload is old".
    label: str | None


class AccessRoleOutcomeRead(BaseSchema):
    """What one rung gets on one route, replayed through the kernel guard's own decision."""

    role: str
    allowed: bool
    #: A stable slug, not prose: ``allowed``, ``public``, ``no_policy``, ``unauthenticated``,
    #: ``unregistered_role``, ``rank``, or ``grant`` (clears the floor, needs the named
    #: permission). A pane dispatches on this; it must never match on an English sentence.
    reason: str


class AccessOperationRead(BaseSchema):
    """What a route does, in the source language (ADR 0102)."""

    id: str
    label: str


class AccessEndpointRead(BaseSchema):
    """One mounted route and the authority that applies to it."""

    path: str
    methods: list[str]
    requirement: str
    extra_permissions: list[str]
    name: str
    #: ``None`` where the route declares no operation, which a pane renders as unexplained
    #: rather than guessing a label from the route name.
    operation: AccessOperationRead | None
    by_role: list[AccessRoleOutcomeRead]


class AccessPolicyRead(BaseSchema):
    """A module's declared posture. ``public`` decides which of the other fields apply."""

    public: bool
    public_reason: str | None = None
    allows_public_writes: bool | None = None
    authenticated: bool | None = None
    read: str | None = None
    write: str | None = None


class ModuleAccessRead(BaseSchema):
    """Whether a module takes part in per-module role assignment (ADR 0112)."""

    assignable: bool
    label: str | None
    summary: str | None
    #: Set when the module refuses assignment outright, and carries the justification.
    platform_reason: str | None


class AccessModuleRead(BaseSchema):
    """One module's declared authority."""

    name: str
    prefix: str | None
    #: ``None`` when the module declares no policy at all — which the boot refuses for a
    #: module with a router, so a pane showing this is showing a real misconfiguration.
    policy: AccessPolicyRead | None
    permissions: list[str]
    #: ``None`` where the module has not declared: the secure default, not a gap.
    access: ModuleAccessRead | None
    endpoints: list[AccessEndpointRead]


class AccessModelRead(BaseSchema):
    """The declared authority surface: the ladder, the permissions, and every module."""

    roles: list[AccessRoleRead]
    permissions: list[AccessPermissionRead]
    modules: list[AccessModuleRead]
