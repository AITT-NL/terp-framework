"""``journals`` manifest — an owner-scoped example resource (ADR 0029).

``Policy.default()`` gives the coarse role gate (authenticated VIEWER reads, EDITOR
writes). The **per-row** ownership gate (only the owner of a given entry may edit or
delete it) is enforced by ``BaseService`` from the ``OwnedMixin`` trait, layered on top
of that role tier — so two different EDITORs both clear the policy guard, yet one
cannot modify the other's entry.
"""

from __future__ import annotations

from terp.core import ModuleSpec, Policy

from app.modules.journals.router import router

module = ModuleSpec(
    name="journals",
    router=router,
    policy=Policy.default(),
)
