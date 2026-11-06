from sqlalchemy import Index, text
from sqlmodel import Field
from terp.core import BaseTable, SoftDeleteMixin


class Note(BaseTable, SoftDeleteMixin, table=True):
    __table_args__ = (
        Index(
            'uq_note_slug_live',
            'slug',
            unique=True,
            postgresql_where=text('deleted_at IS NULL'),
            sqlite_where=text('deleted_at IS NULL'),
        ),
    )

    slug: str = Field(max_length=80)
