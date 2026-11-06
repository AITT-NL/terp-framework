from sqlmodel import Field
from terp.core import BaseTable


class LedgerEntry(BaseTable, table=True):
    amount_cents: int = Field(default=0)
