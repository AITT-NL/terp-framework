import uuid

from sqlmodel import Field
from terp.core import BaseTable, OnDelete, Ref, SoftDeleteMixin


class Invoice(BaseTable, SoftDeleteMixin, table=True):
    number: str = Field(max_length=50)


class InvoiceLine(BaseTable, table=True):
    invoice_id: uuid.UUID | None = Ref(
        "invoice.id", on_delete=OnDelete.SET_NULL, default=None
    )
