from datetime import datetime

from sqlalchemy import DateTime
from sqlmodel import Field

from terp.core import BaseTable


class Note(BaseTable, table=True):
    title: str = Field(max_length=200)
    # The column type pins the zone, so the stored moment stays unambiguous.
    due_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
