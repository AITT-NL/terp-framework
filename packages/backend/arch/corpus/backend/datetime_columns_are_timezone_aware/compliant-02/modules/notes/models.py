from datetime import datetime

from sqlalchemy import Column
from sqlmodel import Field

from terp.core import BaseTable, UtcDateTime


class Note(BaseTable, table=True):
    title: str = Field(max_length=200)
    # Terp's own timestamp type stores the instant as UTC on every dialect and has no
    # switch to get wrong, so naming it is the whole answer, as the class or as a call.
    due_at: datetime | None = Field(default=None, sa_type=UtcDateTime)
    starts_at: datetime = Field(sa_column=Column(UtcDateTime(), nullable=False))
