"""``notes`` manifest — the entire public surface a module exposes.

``Policy.default()`` gives secure-by-default authz: authenticated reads (VIEWER),
mutations require EDITOR. The composition root mounts the router behind a guard
derived from this policy.
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
    policy=Policy.default(),
    emits=[NOTE_CREATED],
)
