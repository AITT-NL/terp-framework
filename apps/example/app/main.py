"""Example app entrypoint."""

from __future__ import annotations

import functools
import pathlib

from fastapi import FastAPI
from starlette.middleware import Middleware

from terp.capabilities.access import enforce_permission
from terp.capabilities.audit import persist_audit
from terp.capabilities.auth import tenant_from_bearer
from terp.capabilities.eventbus import dispatch_in_process
from terp.capabilities.realtime import configure_realtime
from terp.capabilities.tenancy import TenantMiddleware
from terp.core import ModuleSpec, create_app, settings
from terp.migrations import assert_migrations_current

from app.auth import (
    login_module,
    me_module,
    oidc_module,
    principal_provider,
    realtime_message_session_provider,
    realtime_principal_validator,
    throttle_store,
)
from app import realtime as _realtime_channels  # noqa: F401 (registers typed channels)
from app.modules.journals.module import module as journals_module
from app.modules.notes.module import module as notes_module
from app.modules.projects.module import module as projects_module
from app.modules.tasks.module import module as tasks_module
from control_plane import base_control_plane, control_plane


_BASE_CAPABILITIES = ("access", "audit", "groups", "users")
_REALTIME_CAPABILITIES = (*_BASE_CAPABILITIES, "realtime")


def _create(
    *module_specs: ModuleSpec,
    title: str,
    capability_names: tuple[str, ...],
    plane=control_plane,
    job_queue=None,
) -> FastAPI:
    """Build the app with the example's full production-grade wiring, mounting *module_specs*.

    Tenancy is composed through the sanctioned middleware seam (ADR 0021):
    ``TenantMiddleware`` binds the request tenant from the verified token, so the
    tenant-scoped ``projects`` module is isolated per tenant with no ad-hoc
    ``add_middleware`` anywhere in app code.

    Outside local development the app installs the fail-closed migration boot guard
    (ADR 0027): ``assert_migrations_current`` refuses to start when any package's
    schema is behind its code — the installed capabilities *and*, because an
    ``app_root`` is passed, this app's own modules — so a deploy that skipped
    ``terp migrate upgrade`` fails loudly instead of serving a stale schema.

    Session revocation is required at boot (``require_token_revocation=True``, ADR 0031):
    ``principal_provider`` re-validates every token against the store, so a deactivated /
    demoted / password-reset / logged-out user is rejected mid-session; if a refactor ever
    swapped in the stateless provider, the boot would fail closed rather than silently
    regressing to TTL-bounded stale tokens.

    One ``throttle_store`` (ADR 0036) backs both the request rate limiter and the login
    lockout; in-memory here, it is the seam a multi-instance deploy swaps for a shared
    backend so the limits stay correct across workers.
    """
    return create_app(
        list(module_specs),
        title=title,
        principal_provider=principal_provider,
        discover_capabilities=True,
        capability_names=capability_names,
        control_plane=plane,
        audit_sink=persist_audit,
        event_dispatcher=dispatch_in_process,
        job_queue=job_queue,
        permission_enforcer=enforce_permission,
        middleware=[Middleware(TenantMiddleware, resolve_tenant=tenant_from_bearer)],
        require_token_revocation=True,
        throttle_store=throttle_store,
        migration_check=(
            functools.partial(
                assert_migrations_current,
                app_root=pathlib.Path(__file__).resolve().parent,
                package="app",
            )
            if settings.is_production
            else None
        ),
    )


def build() -> FastAPI:
    """The full example app: login + /me, this app's domain modules, and the discovered capabilities."""
    import app.webhooks  # noqa: F401  (registers the NOTE_CREATED -> webhook fan-out subscriber)
    from terp.capabilities.outbox import OutboxJobQueue

    # The dev-only SSO module is None in production (see app/auth.py).
    modules = [login_module, me_module]
    if oidc_module is not None:
        modules.append(oidc_module)

    _realtime_channels.register_realtime_channels()
    configure_realtime(
        permission_enforcer=enforce_permission,
        principal_validator=realtime_principal_validator,
        message_session_provider=realtime_message_session_provider,
    )
    return _create(
        *modules,
        notes_module,
        tasks_module,
        projects_module,
        journals_module,
        title="Terp example app",
        capability_names=(*_REALTIME_CAPABILITIES, "files", "webhooks"),
        plane=control_plane,
        job_queue=OutboxJobQueue(),
    )


def build_base_profile() -> FastAPI:
    """The base-profile surface only: login + /me + required base capabilities, with NONE of
    this app's domain modules or optional capability routers.

    ``terp openapi --app app.main:build_base_profile`` exports this as the frontend contract
    (``packages/frontend/contract/openapi.json``), so the bundled ``@terpjs/contract`` client types the
    endpoints in the reusable base profile — not this example's notes / tasks / projects / journals
    and not optional installed capability routers such as webhooks. An app that wants its own
    endpoints typed generates its own schema (``npm run generate``) and passes those ``paths`` to
    ``useTerpClient`` (ADR 0041).
    """
    return _create(
        login_module,
        me_module,
        title="Terp base profile",
        capability_names=_BASE_CAPABILITIES,
        plane=base_control_plane,
    )


app = build()
