from sqlmodel import Field
from terp.core import BaseTable, TenantScopedMixin


class Project(BaseTable, TenantScopedMixin, table=True):
    name: str = Field(max_length=200)
