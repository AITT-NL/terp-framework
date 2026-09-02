"""``notes`` manifest — the entire public surface a module exposes.

``Policy.default()`` gives secure-by-default authz: authenticated reads (VIEWER),
mutations require EDITOR. The composition root mounts the router behind a guard
derived from this policy.

The delete route then adds a **named permission** on top of that write tier (see
``control_plane/permissions.py``), which is why ``requires`` names the ``access``
capability: the route imports ``require_permission`` from it, and the declared edge
(ADR 0087) is what says out loud that this module does not work without it. The boot
refuses to mount a module whose declared dependency is not installed, so the
requirement cannot silently degrade into an unguarded delete.
"""

from __future__ import annotations

from terp.core import ModuleSpec, Policy

from app.modules.notes.router import router
from app.modules.notes.service import NoteService
from control_plane.events import NOTE_CREATED

module = ModuleSpec(
    name="notes",
    router=router,
    services=(NoteService,),
    requires=("access",),
    policy=Policy.default(),
    emits=[NOTE_CREATED],
)
