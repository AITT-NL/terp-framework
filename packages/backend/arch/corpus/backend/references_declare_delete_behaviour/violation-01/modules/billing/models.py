import uuid

from sqlmodel import Field
from terp.core import BaseTable


class Invoice(BaseTable, table=True):
    number: str = Field(max_length=50)


class InvoiceLine(BaseTable, table=True):
    invoice_id: uuid.UUID = Field(foreign_key="invoice.id")
