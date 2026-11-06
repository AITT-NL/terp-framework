from terp.core import BaseService

from .models import Note


class NoteService(BaseService[Note]):
    model = Note

    def may_edit(self, note: Note, actor) -> bool:
        """Object-level authorization written inline, keyed on the stamp."""
        return note.created_by_id == actor.id
