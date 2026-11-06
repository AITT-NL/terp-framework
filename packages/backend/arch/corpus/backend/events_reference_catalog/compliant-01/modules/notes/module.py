from control_plane.events import NOTE_CREATED
from terp.core import ModuleSpec, Policy, Roles

spec = ModuleSpec(
    name="notes",
    router=router,
    policy=Policy(read=Roles.VIEWER, write=Roles.EDITOR),
    emits=[NOTE_CREATED],
)
