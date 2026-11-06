import uuid

from sqlmodel import Field
from terp.core import BaseTable, OnDelete, Ref


class Invoice(BaseTable, table=True):
    number: str = Field(max_length=50)


class InvoiceLine(BaseTable, table=True):
    invoice_id: uuid.UUID = Ref("invoice.id", on_delete=OnDelete.CASCADE)
