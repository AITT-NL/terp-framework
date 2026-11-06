import traceback

from terp.core import BaseService
from terp.core.errors import ValidationFailedError

from .models import Note


class NoteService(BaseService[Note]):
    model = Note

    def import_note(self, payload: str) -> Note:
        try:
            return self._parse(payload)
        except ValueError:
            raise ValidationFailedError(traceback.format_exc()) from None

    def _parse(self, payload: str) -> Note:
        return Note(body=payload)
