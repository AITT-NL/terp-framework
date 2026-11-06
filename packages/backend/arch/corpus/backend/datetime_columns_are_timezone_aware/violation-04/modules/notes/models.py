from datetime import datetime

from sqlalchemy import DateTime
from sqlmodel import Field

from terp.core import BaseTable


class Note(BaseTable, table=True):
    title: str = Field(max_length=200)
    # timezone=True keeps the zone on PostgreSQL but stores the wall time on SQLite, so
    # the instant this row records depends on where it was written. UtcDateTime is the
    # same column type in the database, so the replacement needs no migration.
    due_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
