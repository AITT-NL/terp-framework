from datetime import datetime

from sqlalchemy import Column
from sqlmodel import Field

import terp.core as core
from terp.core import BaseTable
from terp.core import UtcDateTime as Instant


class Note(BaseTable, table=True):
    title: str = Field(max_length=200)
    # The framework's own timestamp type counts however the file reaches it: under an
    # alias, or through the module it comes from.
    due_at: datetime | None = Field(default=None, sa_type=Instant())
    starts_at: datetime = Field(sa_column=Column(core.UtcDateTime(), nullable=False))
