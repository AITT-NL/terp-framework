from sqlmodel import select

from terp.capabilities.access import ModuleRole


class NoteService:
    def rung(self, session, subject_id):
        return session.exec(
            select(ModuleRole).where(ModuleRole.subject_id == subject_id)
        ).first()
