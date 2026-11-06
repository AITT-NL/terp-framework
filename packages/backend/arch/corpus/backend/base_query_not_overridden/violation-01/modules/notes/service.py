from terp.core import BaseService


class NoteService(BaseService):
    model = Note

    def base_query(self):
        return super().base_query().where(Note.archived == False)
