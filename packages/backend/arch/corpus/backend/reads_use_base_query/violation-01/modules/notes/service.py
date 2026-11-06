from sqlmodel import select
from terp.core import BaseService


class NoteService(BaseService):
    model = Note

    def find_by_slug(self, session, slug):
        return session.exec(select(Note).where(Note.slug == slug)).first()
