"""``tasks`` manifest."""

from __future__ import annotations

from terp.core import ModuleSpec, Policy

from app.modules.tasks import event_handlers  # noqa: F401  (registers subscribers)
from app.modules.tasks.router import router
from app.modules.tasks.service import TaskService
from control_plane.events import NOTE_CREATED

module = ModuleSpec(
    name="tasks",
    router=router,
    services=(TaskService,),
    policy=Policy.default(),
    subscribes=[NOTE_CREATED],
)
