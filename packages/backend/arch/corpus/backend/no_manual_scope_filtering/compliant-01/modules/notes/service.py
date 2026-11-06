from terp.core import BaseService


class NoteService(BaseService):
    model = Note

    def visible(self, session):
        return session.exec(self.base_query())
