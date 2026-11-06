from sqlmodel import select
from terp.core import BaseService


class TagService(BaseService):
    model = Tag

    def find_by_label(self, session, label):
        return session.exec(select(Tag).where(Tag.label == label)).first()
