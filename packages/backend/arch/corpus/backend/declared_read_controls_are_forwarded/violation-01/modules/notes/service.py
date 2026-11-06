from terp.core import BaseService, SortField


class NoteService(BaseService):
    model = Note
    sortable = (
        SortField("name", Note.name),
        SortField("created_at", Note.created_at),
    )
