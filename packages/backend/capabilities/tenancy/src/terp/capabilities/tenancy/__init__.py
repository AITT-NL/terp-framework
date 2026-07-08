"""terp.capabilities.tenancy — tenant scoping as a capability (kernel stays agnostic).

The kernel ships no tenant column, predicate, or scoping model. This capability
adds them: a model becomes tenant-scoped by mixing in :class:`TenantScopedMixin`;
the capability registers a **row-scope predicate** into the kernel's scope registry,
so every read of a tenant-scoped model is filtered to the current tenant centrally
(no ``base_query`` override, no ``super()``). Its service extends
:class:`TenantScopedService`, which stamps ``tenant_id`` on create — no kernel change.

The current tenant is held in a :class:`~contextvars.ContextVar` set via
:func:`tenant_context`. In an HTTP app, :class:`TenantMiddleware` binds it once
per request from the caller's verified token (the app supplies the resolver, e.g.
``terp.capabilities.auth.tenant_from_bearer``); tests set it directly. A missing
context fails closed: scoped reads return nothing and scoped writes raise
:class:`TenantContextError`.
"""

from __future__ import annotations

from terp.capabilities.tenancy.context import (
    TenantContextError,
    current_tenant_id,
    require_tenant,
    tenant_context,
)
from terp.capabilities.tenancy.middleware import TenantMiddleware, TenantResolver
from terp.capabilities.tenancy.models import TenantScopedMixin
from terp.capabilities.tenancy.service import TenantScopedService

__all__ = [
    "TenantContextError",
    "TenantMiddleware",
    "TenantResolver",
    "TenantScopedMixin",
    "TenantScopedService",
    "current_tenant_id",
    "require_tenant",
    "tenant_context",
]
