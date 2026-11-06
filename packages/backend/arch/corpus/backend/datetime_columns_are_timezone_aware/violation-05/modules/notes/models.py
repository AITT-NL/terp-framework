from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy.types import TypeDecorator
from sqlmodel import Field

from terp.core import BaseTable


class UtcDateTime(TypeDecorator):
    # Named like the framework's type, but nothing holds it to storing UTC: this one
    # stores the wall time it is handed, with no zone at all.
    impl = DateTime
    cache_ok = True


class Note(BaseTable, table=True):
    title: str = Field(max_length=200)
    due_at: datetime | None = Field(default=None, sa_type=UtcDateTime())
