from terp.core import BaseService, FilterField, SortField


class NoteService(BaseService):
    model = Note
    filterable = (FilterField("author_id", Note.author_id),)
    sortable = (SortField("created_at", Note.created_at),)
