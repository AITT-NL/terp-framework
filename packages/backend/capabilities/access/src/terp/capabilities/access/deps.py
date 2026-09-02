"""``require_permission`` — a fail-closed, fine-grained authorization dependency.

The module-level ``Policy`` guard enforces the coarse role ladder; this dependency
enforces an **open, app-defined permission** on a single route or router, on top
of (or instead of) a role. It is the runtime half of access's two-layer control:
deny-by-default — an unauthenticated caller gets 401, an authenticated caller
without the grant gets 403::

    from control_plane.permissions import REPORTS_EXPORT
    from terp.capabilities.access import require_permission

    @router.post("/export", dependencies=[Depends(require_permission(REPORTS_EXPORT))])
    def export(...): ...

The reference is a typed :class:`~terp.core.Permission` from the app's control plane,
not a bare string: the ``no_adhoc_permission_literals`` architecture rule refuses the
literal, and a declared permission is the only kind ``terp grant`` can offer or a
``Policy`` can name. Permission names are dotted (``reports.export``); the colon form
this docstring once showed is rejected by ``Permission``'s own validator.

It reads the caller through the kernel's public ``get_principal`` seam, which
``create_app`` points at the configured provider (e.g. the auth capability), so
this capability never imports auth.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import Depends
from sqlmodel import Session

from terp.core import (
    AuthenticationError,
    PermissionDeniedError,
    Permission,
    Principal,
    SessionDep,
    get_principal,
    mark_required_permission,
    register_permission_projector,
)

from terp.capabilities.access.service import AccessService

_service = AccessService()


def require_permission(permission: str | Permission) -> Callable[..., None]:
    """Build a dependency requiring *permission* (deny-by-default).

    ``Permission`` is the path an app should take, and the one the guide now teaches: the
    ``no_adhoc_permission_literals`` rule refuses a bare literal at a ``require_permission``
    call in app code, so the typed constant from the control plane is the only form that
    passes the gate.

    ``str`` stays in the signature because two callers legitimately have only a name: the
    kernel guard's enforcer seam, which is handed the name the ``Policy`` resolved, and an
    operator revoking a permission the app has since stopped declaring. It is not a second
    authoring style — the rule already closed that — and this note used to say the rule
    could not yet guide modules to the control plane, which stopped being true when it
    started refusing the literal.
    """

    permission_name = permission.name if isinstance(permission, Permission) else permission

    def dependency(
        session: SessionDep,
        principal: Principal | None = Depends(get_principal),
    ) -> None:
        if principal is None:
            raise AuthenticationError()
        if not _service.has_permission(session, principal.id, permission_name):
            raise PermissionDeniedError()

    # Introspection marker (never a control): `terp inspect access` reads this to
    # surface route-level permission requirements in the access graph.
    return mark_required_permission(dependency, permission_name)


def enforce_permission(
    session: Session, subject_id: uuid.UUID, permission_name: str
) -> bool:
    """Per-subject permission check for the kernel guard (the ``create_app`` seam).

    Pass to ``create_app(permission_enforcer=enforce_permission)`` so a ``Policy``
    that requires a ``Permission`` is enforced as a real grant (deny-by-default),
    never silently degraded to the permission's role rank. Returns whether
    *subject_id* currently holds *permission_name*.
    """
    return _service.has_permission(session, subject_id, permission_name)


def project_granted_permissions(session: Session, subject_id: uuid.UUID) -> tuple[str, ...]:
    """Every permission *subject_id* holds, for the ``/me`` projection (ADR 0096).

    The read-only counterpart of :func:`enforce_permission`: the same expanded subject set
    (direct grants plus any a registered expander maps the caller to), returned as names
    instead of a yes/no. Registered below, so ``GET /me`` reports it without the auth or
    identity capability importing this one.

    It is a **display** projection, never a decision: the guard still calls
    :func:`enforce_permission` on every request. Reporting a permission the caller holds
    cannot widen anything — a client that treats this list as authority has moved the gate
    to the wrong side of the wire, which is why the DTO field says so too.
    """
    return tuple(sorted(_service.permissions_for(session, subject_id)))


# Registered at import, like a scope predicate: an app that mounts this capability gets the
# projection without wiring it, and one that does not projects nothing.
register_permission_projector(project_granted_permissions)


__all__ = ["enforce_permission", "project_granted_permissions", "require_permission"]
