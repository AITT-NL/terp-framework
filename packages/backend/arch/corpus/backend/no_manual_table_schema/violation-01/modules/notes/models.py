from sqlmodel import Field
from terp.core import BaseTable


class Note(BaseTable, table=True):
    __table_args__ = {"schema": "notes"}

    title: str = Field(max_length=200)
