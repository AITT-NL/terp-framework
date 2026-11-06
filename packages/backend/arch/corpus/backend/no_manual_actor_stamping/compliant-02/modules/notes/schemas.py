import uuid

from terp.core import BaseSchema


class NoteRead(BaseSchema):
    """A read DTO may EXPOSE the actor-stamp columns (annotation only) —
    only attribute access (set / compare) is policed."""

    title: str
    created_by_id: uuid.UUID | None
    modified_by_id: uuid.UUID | None
