from sqlmodel import Field
from terp.core import BaseTable


class Attachment(BaseTable, table=True):
    """Not tenant-scoped (no TenantScopedMixin) — a plain BaseService is fine."""

    name: str = Field(max_length=200)
