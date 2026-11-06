from terp.core import BaseService, FilterField


class NoteService(BaseService):
    model = Note
    filterable = (
        FilterField("author_id", Note.author_id),
        FilterField("created_from", Note.created_at, op="gte"),
    )
