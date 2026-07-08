"""``TenantMiddleware`` — bind the per-request tenant from the caller's request.

A **pure-ASGI** middleware (deliberately not ``BaseHTTPMiddleware``, which runs the
downstream app in a separate task and so would not propagate a ``ContextVar`` set
here to the endpoint). It calls an app-supplied ``resolve_tenant(request)`` — e.g.
``terp.capabilities.auth.tenant_from_bearer`` — and runs the request inside
:func:`~terp.capabilities.tenancy.tenant_context`, resetting it afterwards.

The tenancy capability stays decoupled from auth: it knows *how* to bind a tenant
per request, not *how* to read one. The app wires the two together through the
sanctioned ``create_app`` middleware seam (ADR 0021) — never a bare
``add_middleware`` (the ``no_adhoc_middleware`` rule forbids it)::

    from starlette.middleware import Middleware
    from terp.capabilities.auth import tenant_from_bearer

    app = create_app(
        specs,
        principal_provider=get_principal,
        middleware=[Middleware(TenantMiddleware, resolve_tenant=tenant_from_bearer)],
    )

Fail-closed: a request that resolves to no tenant runs with an empty context, so
every ``TenantScopedService`` read returns nothing and writes raise.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from terp.capabilities.tenancy.context import tenant_context

TenantResolver = Callable[[Request], uuid.UUID | None]


class TenantMiddleware:
    """ASGI middleware that binds ``tenant_context`` from *resolve_tenant* per request."""

    def __init__(self, app: ASGIApp, *, resolve_tenant: TenantResolver) -> None:
        self.app = app
        self._resolve_tenant = resolve_tenant

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        tenant = self._resolve_tenant(Request(scope))
        with tenant_context(tenant):
            await self.app(scope, receive, send)


__all__ = ["TenantMiddleware", "TenantResolver"]
