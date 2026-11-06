import uuid

from sqlalchemy import ForeignKeyConstraint
from terp.core import BaseTable


class Invoice(BaseTable, table=True):
    number: str


class InvoiceLine(BaseTable, table=True):
    __table_args__ = (ForeignKeyConstraint(["invoice_id"], ["invoice.id"]),)

    invoice_id: uuid.UUID
