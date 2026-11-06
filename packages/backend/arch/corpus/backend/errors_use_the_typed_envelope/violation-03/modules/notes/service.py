from starlette.exceptions import HTTPException

from terp.core import BaseService

from .models import Note


class NoteService(BaseService[Note]):
    model = Note

    def archive(self, note_id: str) -> None:
        raise HTTPException(403, "Archiving is disabled")
