import uuid

from terp.core import BaseSchema, Personal


class CustomerRead(BaseSchema):
    id: uuid.UUID
    email: str = Personal()
    phone_number: str | None = Personal(default=None)
