from sqlalchemy import UniqueConstraint
from sqlmodel import Field
from terp.core import BaseTable, SoftDeleteMixin


class ArchivableRow(BaseTable, SoftDeleteMixin):
    pass


class Note(ArchivableRow, table=True):
    __table_args__ = (UniqueConstraint('slug'),)

    slug: str = Field(max_length=80)
