from sqlmodel import Field
from terp.core import BaseSchema


class NoteCreate(BaseSchema):
    title: str = Field(max_length=200)
