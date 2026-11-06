from control_plane.events import NOTE_CREATED, NOTE_DELETED
from terp.core import ModuleSpec, Policy, Roles, emit

spec = ModuleSpec(
    name="notes",
    router=router,
    policy=Policy(read=Roles.VIEWER, write=Roles.EDITOR),
    emits=[NOTE_CREATED, NOTE_DELETED],
)


def archive(session, note):
    emit(session, event=NOTE_DELETED, payload={"id": str(note.id)})
