from app.control_plane.permissions import NOTES_WRITE

spec = ModuleSpec(name='notes', policy=Policy(write=NOTES_WRITE))
