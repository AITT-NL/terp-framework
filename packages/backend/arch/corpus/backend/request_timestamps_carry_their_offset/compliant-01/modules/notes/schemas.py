from datetime import datetime

from terp.core import BaseSchema


class ReadingCreate(BaseSchema):
    # A plain timestamp field needs nothing: a client's value without its UTC offset is
    # refused where it enters, with the fix named.
    taken_at: datetime
    checked_at: datetime | None = None
