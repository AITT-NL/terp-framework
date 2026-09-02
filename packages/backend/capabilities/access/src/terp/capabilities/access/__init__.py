"""terp.capabilities.access — RBAC permission grants + ``require_permission``.

The fourth opt-in capability and the remaining base-profile authorization piece.
The kernel ``Policy`` guard enforces the coarse, global role ladder; this
capability adds **fine-grained, per-permission** authorization on top:

* a persisted :class:`Grant` (subject ↦ open, app-defined permission token),
* an :class:`AccessService` (idempotent ``grant`` / ``revoke`` / ``has_permission``),
* a fail-closed :func:`require_permission` dependency modules mount on a route,
* a **self-registering**, admin-only ``access`` router to administer grants.

It also owns the other half of "who may do what": a :class:`ModuleRole` records that a
subject holds a rung *inside one module*, and :func:`resolve_module_rank` fills the kernel's
``module_rank_resolver`` seam so the guard can let that rung raise the caller's authority in
that module and nowhere else (ADR 0112). The two halves answer different questions — a grant
is a named capability, a module role is a tier within a boundary — and neither is expressible
as the other, which is why both exist.

It depends only on ``terp-core``: it reads the caller through the kernel's public
``get_principal`` seam (which ``create_app`` points at the configured provider),
so it never imports the auth capability.
"""

from __future__ import annotations

from terp.capabilities.access.deps import (
    enforce_permission,
    project_granted_permissions,
    require_permission,
)
from terp.capabilities.access.expansion import (
    SubjectExpander,
    register_subject_expander,
    reset_subject_expanders,
    subject_ids_for,
)
from terp.capabilities.access.models import Grant, ModuleRole
from terp.capabilities.access.module_roles import (
    ModuleRoleService,
    assignable_modules,
    resolve_module_rank,
    validate_assignment,
)
from terp.capabilities.access.operations import (
    ACCESS_CREATE_GRANT,
    ACCESS_DELETE_GRANT,
    ACCESS_GET_MODEL,
    ACCESS_LIST_GRANTS,
)
from terp.capabilities.access.router import module, router
from terp.capabilities.access.schemas import (
    AccessModelRead,
    GrantCreate,
    GrantRead,
    GrantUpdate,
)
from terp.capabilities.access.service import AccessService

__all__ = [
    "ACCESS_CREATE_GRANT",
    "ACCESS_DELETE_GRANT",
    "ACCESS_GET_MODEL",
    "ACCESS_LIST_GRANTS",
    "AccessModelRead",
    "AccessService",
    "Grant",
    "GrantCreate",
    "GrantRead",
    "GrantUpdate",
    "ModuleRole",
    "ModuleRoleService",
    "SubjectExpander",
    "assignable_modules",
    "enforce_permission",
    "project_granted_permissions",
    "module",
    "register_subject_expander",
    "require_permission",
    "reset_subject_expanders",
    "resolve_module_rank",
    "router",
    "subject_ids_for",
    "validate_assignment",
]
