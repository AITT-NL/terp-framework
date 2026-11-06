from terp.capabilities.access import AccessService


class NoteService:
    def __init__(self) -> None:
        self.access = AccessService()
