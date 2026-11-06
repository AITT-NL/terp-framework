from sqlmodel import Field
from terp.core import BaseTable


class Customer(BaseTable, table=True):
    email: str = Field(max_length=320, unique=True)
