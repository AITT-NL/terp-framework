import uuid

from sqlmodel import Field
from terp.core import BaseTable


class RunRequest(BaseTable, table=True):
    """The row records its own lifecycle; custody is the platform's, keyed on the row."""

    __tablename__ = "run_request"

    connection_id: uuid.UUID = Field(index=True)
    status: str = Field(max_length=16, index=True)
