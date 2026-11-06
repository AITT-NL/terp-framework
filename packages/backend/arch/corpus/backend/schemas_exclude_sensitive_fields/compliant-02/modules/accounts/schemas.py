from sqlmodel import Field
from terp.core import BaseSchema, BaseTable


class AccountRead(BaseSchema):
    passwordless: bool
    tokens_issued: int
    secretive_mode: bool


class Account(BaseTable, table=True):
    hashed_password: str = Field(max_length=200)
