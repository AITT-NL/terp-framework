from terp.core import BaseService


class NoteService(BaseService):
    model = Note

    def find_by_slug(self, session, slug):
        return session.exec(self.base_query().where(Note.slug == slug)).first()
