from sqlmodel import Field
from terp.core import BaseTable, Personal


class Customer(BaseTable, table=True):
    email: str = Personal(max_length=320, unique=True)
    phone_number: str | None = Personal(default=None, max_length=32)
    email_verified: bool = False
    phone_count: int = 0
    postcode: str = Field(default="", max_length=12)
    company_name: str = Field(default="", max_length=200)
