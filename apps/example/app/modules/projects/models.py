"""``projects`` table model — a tenant-scoped resource (rows isolated per tenant).

Composes the tenancy capability's
:class:`~terp.capabilities.tenancy.TenantScopedMixin`: ``tenant_id`` is stamped on
create by the scoped service, and every read is filtered to the caller's tenant by
the registered scope predicate (ADR 0017) — the module writes no
``WHERE tenant_id = ...`` clause.
"""

from __future__ import annotations

from sqlmodel import Field

from terp.capabilities.tenancy import TenantScopedMixin
from terp.core import BaseTable


class Project(BaseTable, TenantScopedMixin, table=True):
    """A tenant-scoped project.

    ``id`` / ``created_at`` / ``updated_at`` / ``version`` are inherited from
    ``BaseTable``; ``tenant_id`` from ``TenantScopedMixin``.
    """

    __tablename__ = "project"

    name: str = Field(max_length=200, index=True)
