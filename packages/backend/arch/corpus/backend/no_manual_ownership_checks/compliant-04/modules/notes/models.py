from sqlmodel import Field

from terp.core import BaseTable, OwnedMixin


class OwnedRecord(BaseTable, OwnedMixin):
    """A house base every owned table in this app composes."""


class Note(OwnedRecord, table=True):
    title: str = Field(max_length=200)
