"""``TenantScopedMixin`` — marks a table's rows as belonging to a tenant.

Importing this mixin registers the tenancy row-scope predicate with the kernel's
scope registry, so the runtime read-scope layer is installed as soon as a model opts
into tenancy (ADR 0017). ``TenantScopedService`` still stamps ``tenant_id`` on
create; the mixin owns the read predicate.
"""

from __future__ import annotations

import uuid

from sqlalchemy import false
from sqlmodel import Field, SQLModel
from sqlmodel.sql.expression import SelectOfScalar

from terp.capabilities.tenancy.context import current_tenant_id
from terp.core import register_scope_predicate


class TenantScopedMixin(SQLModel):
    """Mix into a ``BaseTable`` to scope its rows to a tenant.

    Adds a non-null, indexed ``tenant_id``. The registered tenant predicate filters
    every read by the current tenant, and ``TenantScopedService`` stamps it on insert,
    so a model is tenant-scoped purely by inheriting this — the kernel needs no
    tenant-specific import.
    """

    tenant_id: uuid.UUID = Field(index=True, nullable=False)


def _tenant_scope_predicate(
    model: type[SQLModel], query: SelectOfScalar
) -> SelectOfScalar:
    """Filter a tenant-scoped model's reads by the current tenant (registered centrally)."""
    if issubclass(model, TenantScopedMixin):
        tenant_id = current_tenant_id()
        if tenant_id is None:
            return query.where(false())
        return query.where(model.tenant_id == tenant_id)  # type: ignore[attr-defined]  # arch-allow-no-manual-scope-filtering: this IS the central tenant predicate the rule points app modules to
    return query


register_scope_predicate(_tenant_scope_predicate)


__all__ = ["TenantScopedMixin"]
