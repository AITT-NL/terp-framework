from sqlmodel import Field
from terp.core import BaseTable


class Tag(BaseTable, table=True):
    """No scope trait (SoftDeleteMixin / TenantScopedMixin) — a raw select
    of an unscoped model drops no row scope and is not policed."""

    label: str = Field(max_length=40)
