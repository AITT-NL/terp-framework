import datetime

from terp.core import BaseSchema


class NoteRead(BaseSchema):
    """A read DTO may EXPOSE a managed scope column (annotation only) —
    only attribute access (filter / set / compare) is policed."""

    title: str
    deleted_at: datetime.datetime | None
    tenant_id: str | None
