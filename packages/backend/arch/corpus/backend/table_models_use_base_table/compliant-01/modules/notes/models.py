from sqlmodel import Field
from terp.core import BaseTable


class Note(BaseTable, table=True):
    title: str = Field(max_length=200)
