from datetime import datetime
from typing import Optional

from sqlalchemy import Column
from sqlmodel import Field

import terp
from terp.core import BaseTable


class Note(BaseTable, table=True):
    title: str = Field(max_length=200)
    # Reached through the terp package, after the column's own name, the framework's type
    # stores the instant as UTC all the same.
    due_at: Optional[datetime] = Field(
        default=None, sa_column=Column("due_at", terp.core.UtcDateTime(), nullable=True)
    )
