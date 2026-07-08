"""``tasks`` manifest."""

from __future__ import annotations

from terp.core import ModuleSpec, Policy

from app.modules.tasks import event_handlers  # noqa: F401  (registers subscribers)
from app.modules.tasks.router import router
from control_plane.events import NOTE_CREATED

module = ModuleSpec(
    name="tasks",
    router=router,
    policy=Policy.default(),
    subscribes=[NOTE_CREATED],
)
