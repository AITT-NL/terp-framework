from terp.core import BaseService
from terp.core.errors import ConflictError

from .models import Note


class NoteService(BaseService[Note]):
    model = Note

    def publish(self, note_id: str) -> None:
        try:
            self._publish(note_id)
        except RuntimeError as exc:
            raise ConflictError(message=repr(exc)) from exc

    def _publish(self, note_id: str) -> None:
        return None
