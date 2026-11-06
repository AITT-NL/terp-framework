import uuid

from sqlmodel import Field
from terp.core import BaseSchema


class NoteCreate(BaseSchema):
    id: uuid.UUID
    title: str = Field(max_length=200)
