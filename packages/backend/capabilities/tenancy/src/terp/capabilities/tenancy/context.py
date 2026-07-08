"""The current-tenant context (a ``ContextVar`` + helpers)."""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import Iterator
from contextvars import ContextVar

from terp.core import AppError

_current_tenant: ContextVar[uuid.UUID | None] = ContextVar(
    "terp_current_tenant", default=None
)


class TenantContextError(AppError):
    """Raised when a tenant-scoped operation runs with no tenant in context."""

    status_code = 500
    code = "tenant_context_missing"
    default_message = "No tenant is set for the current operation."


def current_tenant_id() -> uuid.UUID | None:
    """Return the tenant for the active operation, or ``None``."""
    return _current_tenant.get()


def require_tenant() -> uuid.UUID:
    """Return the current tenant, or raise :class:`TenantContextError`."""
    tenant = _current_tenant.get()
    if tenant is None:
        raise TenantContextError()
    return tenant


@contextlib.contextmanager
def tenant_context(tenant_id: uuid.UUID | None) -> Iterator[None]:
    """Bind *tenant_id* as the current tenant for the duration of the block."""
    token = _current_tenant.set(tenant_id)
    try:
        yield
    finally:
        _current_tenant.reset(token)


__all__ = [
    "TenantContextError",
    "current_tenant_id",
    "require_tenant",
    "tenant_context",
]
