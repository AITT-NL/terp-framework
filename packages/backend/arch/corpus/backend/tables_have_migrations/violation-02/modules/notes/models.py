from sqlmodel import Field
from terp.core import BaseTable


class NoteTag(BaseTable, table=True):
    label: str = Field(max_length=40)


class Note(BaseTable, table=True):
    title: str = Field(max_length=200)
