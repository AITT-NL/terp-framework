from terp.core import BaseService, FilterField


class NoteService(BaseService):
    model = Note
    filterable = (FilterField("author_id", Note.author_id),)
