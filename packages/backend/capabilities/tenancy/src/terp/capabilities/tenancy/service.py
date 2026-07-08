"""``TenantScopedService`` — write stamping for tenant-scoped models.

The kernel stays tenancy-agnostic. A model becomes tenant-scoped by mixing in
:class:`~terp.capabilities.tenancy.TenantScopedMixin`, which registers the
**row-scope predicate** with the kernel's scope registry. Reads are therefore
filtered centrally (no ``base_query`` override, no ``super()``, ADR 0017), and this
service only stamps ``tenant_id`` on create (rejecting an absent context).
"""

from __future__ import annotations

from typing import TypeVar

from sqlmodel import Session, SQLModel

from terp.capabilities.tenancy.context import require_tenant
from terp.core import (
    AuditAction,
    BaseService,
    BaseTable,
    BaseUpdateSchema,
)

ModelT = TypeVar("ModelT", bound=BaseTable)
CreateT = TypeVar("CreateT", bound=SQLModel)
UpdateT = TypeVar("UpdateT", bound=BaseUpdateSchema)


class TenantScopedService(BaseService[ModelT, CreateT, UpdateT]):
    """A :class:`~terp.core.BaseService` whose model is tenant-scoped.

    ``model`` must mix in :class:`~terp.capabilities.tenancy.TenantScopedMixin`.
    Reads are filtered to ``current_tenant_id()`` by the registered scope predicate
    (``None`` matches no rows, so a missing context fails closed); this service
    stamps the required tenant on create.
    """

    def create(self, session: Session, data: CreateT) -> ModelT:
        # Route through the audited chokepoint so a tenant-scoped create is audited,
        # actor-stamped, event-hooked, and 409-mapped exactly like every other write.
        # Strip framework-managed columns first (anti over-posting, like BaseService),
        # then stamp the tenant from context -- never from the request body. Stripping
        # tenant_id from the payload also avoids a duplicate-keyword collision with the
        # context-derived value below.
        entity = self.model(
            **self._without_managed_columns(data.model_dump()),
            tenant_id=require_tenant(),
        )
        return self._save(session, entity, AuditAction.CREATED)


__all__ = ["TenantScopedService"]
