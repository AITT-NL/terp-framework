from fastapi import HTTPException

from terp.core import BaseService
from terp.core.errors import NotFoundError

from .models import Note


class NoteService(BaseService[Note]):
    """Naming the framework's error is not raising it.

    An adapter that has to recognise an error the framework itself raised needs
    the type in scope; the rule is about what this module raises, so importing
    it, catching it and re-raising the caught one must all stay silent.
    """

    model = Note

    def fetch_upstream(self, note_id: str) -> dict:
        try:
            return self._call_upstream(note_id)
        except HTTPException:
            raise
        except LookupError as exc:
            raise NotFoundError("Note not found") from exc

    def _call_upstream(self, note_id: str) -> dict:
        return {"id": note_id}
