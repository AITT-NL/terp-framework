from terp.core import BaseService
from terp.core.errors import ConflictError

from .models import Note


class NoteService(BaseService[Note]):
    """The exception's own text belongs in the log half of the envelope.

    ``log_context`` is attached to the log line and never serialised to the
    client, so the operator keeps the driver's message and the caller does not
    get it. That split is the whole point of the rule, so a compliant case has
    to pin it: a detector that refused every mention of the caught exception
    would take this away and leave nowhere for the diagnosis to go.
    """

    model = Note

    def publish(self, note_id: str) -> None:
        try:
            self._publish(note_id)
        except RuntimeError as exc:
            raise ConflictError(
                "This note could not be published.",
                log_context={"cause": str(exc), "note_id": note_id},
            ) from exc

    def _publish(self, note_id: str) -> None:
        return None
