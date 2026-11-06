from datetime import datetime

from sqlmodel import Field

from terp.core import BaseTable


class ArchivedMixin:
    # Declaring the column one class up does not change where it lands: the
    # table still gets a naive timestamp column.
    archived_at: datetime | None = Field(default=None)


class Note(ArchivedMixin, BaseTable, table=True):
    title: str = Field(max_length=200)
