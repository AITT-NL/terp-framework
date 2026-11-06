import uuid

from sqlmodel import Field
from terp.capabilities.files import FileRef
from terp.core import BaseTable


class Note(BaseTable, table=True):
    title: str = Field(max_length=200)
    attachment_file_id: uuid.UUID | None = FileRef()
