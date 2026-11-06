from terp.core import BaseService


class NoteService(BaseService):
    model = Note

    def load(self, session, note_id):
        return session.get(Note, note_id)
