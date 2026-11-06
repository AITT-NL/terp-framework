from terp.capabilities.access import ModuleRoleService


class NoteService:
    def rung(self, session, subject_id):
        return ModuleRoleService().highest_rank(session, subject_id, "notes")
