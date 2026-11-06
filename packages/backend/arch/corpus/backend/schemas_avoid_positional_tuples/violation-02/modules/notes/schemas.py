class NoteCreate(BaseSchema):
    tags: list[tuple[str, str]]
