from datetime import datetime

from sqlalchemy import Column, DateTime
from sqlmodel import Field

from terp.core import BaseTable, UtcDateTime


class Note(BaseTable, table=True):
    title: str = Field(max_length=200)
    # UtcDateTime is named in the call, but the column is built from DateTime(timezone=True):
    # only the type that reaches the column counts.
    due_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True)),
        schema_extra={"stored_as": UtcDateTime.__name__},
    )
