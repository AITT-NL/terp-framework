from terp.core import BaseService


class NoteService(BaseService):
    model = Note

    def business_filters(self):
        return [Note.archived == False]
