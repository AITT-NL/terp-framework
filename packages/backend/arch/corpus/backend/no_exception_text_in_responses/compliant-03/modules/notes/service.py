import logging

from terp.core import BaseService
from terp.core.errors import ValidationFailedError

from .models import Note

logger = logging.getLogger(__name__)


class NoteService(BaseService[Note]):
    """A message built from the request is not a message built from the failure.

    The refused thing is the exception's own text. Interpolating a value the
    caller submitted is ordinary message writing, and a detector that matched
    every f-string inside a handler would refuse it.
    """

    model = Note

    def import_note(self, payload: str, filename: str) -> Note:
        try:
            return self._parse(payload)
        except ValueError as exc:
            logger.exception("import failed for %s", filename)
            raise ValidationFailedError(f"{filename} could not be read.") from exc

    def _parse(self, payload: str) -> Note:
        return Note(body=payload)
