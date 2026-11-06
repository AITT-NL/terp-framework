import uuid

from sqlalchemy import Column, ForeignKey
from sqlmodel import Field
from terp.core import BaseTable


class Invoice(BaseTable, table=True):
    number: str = Field(max_length=50)


class InvoiceLine(BaseTable, table=True):
    invoice_id: uuid.UUID = Field(foreign_key="invoice.id", ondelete="CASCADE")


class InvoiceNote(BaseTable, table=True):
    invoice_id: uuid.UUID = Field(
        sa_column=Column(ForeignKey("invoice.id", ondelete="RESTRICT"))
    )
