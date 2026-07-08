"""terp.capabilities.access — RBAC permission grants + ``require_permission``.

The fourth opt-in capability and the remaining base-profile authorization piece.
The kernel ``Policy`` guard enforces the coarse, global role ladder; this
capability adds **fine-grained, per-permission** authorization on top:

* a persisted :class:`Grant` (subject ↦ open, app-defined permission token),
* an :class:`AccessService` (idempotent ``grant`` / ``revoke`` / ``has_permission``),
* a fail-closed :func:`require_permission` dependency modules mount on a route,
* a **self-registering**, admin-only ``access`` router to administer grants.

It depends only on ``terp-core``: it reads the caller through the kernel's public
``get_principal`` seam (which ``create_app`` points at the configured provider),
so it never imports the auth capability.
"""

from __future__ import annotations

from terp.capabilities.access.deps import enforce_permission, require_permission
from terp.capabilities.access.expansion import (
    SubjectExpander,
    register_subject_expander,
    reset_subject_expanders,
    subject_ids_for,
)
from terp.capabilities.access.models import Grant
from terp.capabilities.access.router import module, router
from terp.capabilities.access.schemas import GrantCreate, GrantRead, GrantUpdate
from terp.capabilities.access.service import AccessService

__all__ = [
    "AccessService",
    "Grant",
    "GrantCreate",
    "GrantRead",
    "GrantUpdate",
    "SubjectExpander",
    "enforce_permission",
    "module",
    "register_subject_expander",
    "require_permission",
    "reset_subject_expanders",
    "router",
    "subject_ids_for",
]
