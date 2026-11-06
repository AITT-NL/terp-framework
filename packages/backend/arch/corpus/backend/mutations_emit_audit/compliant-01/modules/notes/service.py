from terp.core import BaseService


class NoteService(BaseService):
    model = Note

    def archive(self, session, note_id, payload):
        note = self.get(session, note_id)
        return self.update(session, note, payload)
