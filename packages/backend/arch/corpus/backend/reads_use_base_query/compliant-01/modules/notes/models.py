from sqlmodel import Field
from terp.core import BaseTable, SoftDeleteMixin


class Note(BaseTable, SoftDeleteMixin, table=True):
    slug: str = Field(max_length=80)
