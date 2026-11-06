class NoteCreate(BaseSchema):
    title: str = Field(max_length=200)
class NoteRead(BaseSchema):
    title: str
