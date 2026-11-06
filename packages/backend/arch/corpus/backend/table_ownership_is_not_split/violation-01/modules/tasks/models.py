from sqlmodel import Field
from terp.core import BaseTable


class Note(BaseTable, table=True):
    __tablename__ = "notes_note"

    title: str = Field(max_length=200)
