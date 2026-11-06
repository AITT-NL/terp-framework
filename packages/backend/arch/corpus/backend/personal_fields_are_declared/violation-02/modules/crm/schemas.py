import uuid

from terp.core import BaseSchema


class CustomerRead(BaseSchema):
    id: uuid.UUID
    email: str
