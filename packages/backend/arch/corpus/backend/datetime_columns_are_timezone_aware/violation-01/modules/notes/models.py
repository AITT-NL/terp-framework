from datetime import datetime

from sqlmodel import Field

from terp.core import BaseTable


class Note(BaseTable, table=True):
    title: str = Field(max_length=200)
    # No column type is named, so this maps to naive storage: the database
    # drops the zone of whatever aware value the service hands it.
    due_at: datetime | None = Field(default=None, index=True)
