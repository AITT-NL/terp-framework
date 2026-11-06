import uuid

from sqlmodel import Field
from terp.core import BaseTable, OnDelete, Ref


class Account(BaseTable, table=True):
    code: str = Field(max_length=20)


class LedgerEntry(BaseTable, table=True):
    account_id: uuid.UUID = Ref("account.id", on_delete=OnDelete.RESTRICT)


class AuditNote(BaseTable, table=True):
    account_id: uuid.UUID = Ref("account.id", on_delete=OnDelete.NO_ACTION)
