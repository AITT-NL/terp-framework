import datetime

from sqlmodel import Field
from terp.core import BaseUpdateSchema


class CustomerUpdate(BaseUpdateSchema):
    contact_phone_number: str | None = Field(default=None, max_length=32)
    date_of_birth: datetime.date | None = None
