from datetime import datetime

from terp.core import BaseSchema


class LeaseRead(BaseSchema):
    """A read DTO may surface who holds a lease and until when — it declares no column.

    Only a persisted column on a table model is refused; showing an operator what is
    stuck is exactly what the primitive is for.
    """

    holder: str | None
    locked_until: datetime | None
    heartbeat_at: datetime | None
