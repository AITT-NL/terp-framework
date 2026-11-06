"""A small, cohesive service — well under the file-size cap."""

from terp.core import BaseService

from .models import Note


class NoteService(BaseService[Note]):
    model = Note
