from fastapi import HTTPException

from terp.core import BaseService

from .models import Note


class NoteService(BaseService[Note]):
    model = Note

    def get_or_refuse(self, note_id: str) -> Note:
        note = self.get(note_id)
        if note is None:
            raise HTTPException(status_code=404, detail="Note not found")
        return note
