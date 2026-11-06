class ReadingClock:
    # An app's own attribute named timestamps is the app's, whatever object holds it.
    def __init__(self, core: object) -> None:
        self.core = core

    def latest(self) -> object:
        return self.core.timestamps
