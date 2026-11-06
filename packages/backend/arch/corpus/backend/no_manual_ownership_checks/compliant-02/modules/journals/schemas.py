import uuid

from terp.core import BaseSchema


class JournalRead(BaseSchema):
    """A read DTO may EXPOSE owner_id (annotation only) — only attribute
    access (set / filter / compare) is policed."""

    title: str
    owner_id: uuid.UUID | None
