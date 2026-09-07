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


class SubjectRefRead(BaseSchema):
    """Where a right came from: the caller themselves, or a group they belong to."""

    id: uuid.UUID
    #: ``self`` or ``group`` today; an app's own expander may name others. Dispatched on.
    kind: str
    #: ``None`` when the expander did not know one, which a pane renders as the bare id
    #: rather than inventing a label.
    name: str | None


class HeldPermissionRead(BaseSchema):
    """One permission a subject holds, and why."""

    name: str
    #: What holding it buys, from the declared catalog; ``None`` if unlabelled or undeclared.
    label: str | None
    #: ``False`` when the app no longer declares this permission — a stale grant, shown
    #: rather than hidden, because a filtered row is a right nobody can explain.
    declared: bool
    via: SubjectRefRead


class HeldModuleRoleRead(BaseSchema):
    """One per-module rung a subject holds, and why."""

    module: str
    role_rank: int
    #: The declared name for that rank, or ``None`` when the app no longer declares it.
    role: str | None
    #: Whether this is the row that actually decides the subject's authority in the module.
    #: Several can be held at once — one directly, one through a group — and only the highest
    #: has any effect, which is the thing an administrator most often gets wrong.
    effective: bool
    #: Why this row does not apply as written, where that is so: an undeclared rank, or a
    #: module that no longer accepts per-module roles. Empty for an ordinary row.
    stale: list[str]
    via: SubjectRefRead


class SubjectAccessRead(BaseSchema):
    """One subject's effective access, with the provenance of every right.

    The answer to "why can this person do that?", which is the only defence an administrator
    has against an over-broad grant. It reports what is *held*; what that lets someone do on a
    given route is the declared model's question (``GET /model``), and a pane joins the two.

    It deliberately does **not** carry the subject's global rank. That lives in the users
    table, which this capability cannot import — its whole premise is being a leaf the
    identity modules depend on rather than the reverse — and a field nothing here could ever
    fill would be structurally null. A pane already fetches the account to show its detail
    screen, so it has the rank; adding a seam to duplicate it here would be a second source
    of truth for one integer.
    """

    subject_id: uuid.UUID
    #: The caller plus every subject they speak for — the set every right below is drawn from.
    via: list[SubjectRefRead]
    permissions: list[HeldPermissionRead]
    module_roles: list[HeldModuleRoleRead]

