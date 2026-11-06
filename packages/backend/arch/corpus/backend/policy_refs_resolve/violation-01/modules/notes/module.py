from control_plane import permissions as perms
from terp.core import ModuleSpec, Policy

spec = ModuleSpec(
    name="notes",
    router=router,
    policy=Policy(read=perms.NOTES_READ, write=perms.NOTES_WRITE),
)
