from datetime import datetime

from sqlalchemy import DateTime
from sqlmodel import Field

from terp.core import BaseTable


class Note(BaseTable, table=True):
    title: str = Field(max_length=200)
    # An explicit column type that is declared without a timezone is naive
    # storage just as thoroughly as naming no type at all.
    due_at: datetime = Field(sa_type=DateTime(timezone=False))
