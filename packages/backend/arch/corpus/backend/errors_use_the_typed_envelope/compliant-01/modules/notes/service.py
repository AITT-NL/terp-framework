from terp.core import BaseService
from terp.core.errors import ConflictError, NotFoundError

from .models import Note


class NoteService(BaseService[Note]):
    model = Note

    def get_or_refuse(self, note_id: str) -> Note:
        note = self.get(note_id)
        if note is None:
            raise NotFoundError("Note not found")
        return note

    def publish(self, note_id: str) -> Note:
        note = self.get_or_refuse(note_id)
        if note.published:
            raise ConflictError("This note is already published.")
        return note
