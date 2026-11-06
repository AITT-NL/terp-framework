from datetime import datetime

from sqlmodel import Field
from terp.core import BaseTable


class RunRequest(BaseTable, table=True):
    """A queue row that re-derives custody on itself: a holder plus a deadline.

    Nothing here can refuse a holder that merely paused: it wakes past its deadline,
    finds its own name still in ``locked_by``, and finishes over the successor that
    already took the work.
    """

    __tablename__ = "run_request"

    status: str = Field(max_length=16, index=True)
    locked_by: str | None = Field(default=None, max_length=128)
    locked_until: datetime | None = None
