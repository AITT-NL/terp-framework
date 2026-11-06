from terp.core import BaseService

from .models import Note


class NoteService(BaseService):
    model = Note
