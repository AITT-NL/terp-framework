from terp.core import BaseService


class NoteService(BaseService):
    model = Note

    async def base_query(self):
        return (await super().base_query()).where(Note.archived == False)
