"""``terp inspect access`` — the Access Graph: one view of who can reach what.

The effective permission story has three layers, and each already has a typed,
enforced source of truth:

1. **Module access** — ``ModuleSpec.policy`` (deny-by-default; ``Policy.public``
   is the justified exception).
2. **Endpoint access** — the policy's read/write requirement applied per HTTP
   method by the kernel guard, plus any route-level
   ``require_permission(...)`` dependency the access capability contributes.
3. **Data visibility / object authority** — model traits (``SoftDeleteMixin``,
   ``OwnedMixin``, ``TenantScopedMixin``, ``ActorStampedMixin``) honored
   centrally by ``BaseService`` and the registered scope / object-authz
   predicates (ADR 0017 / 0029).

This module *projects* those sources into one structured report — JSON-first so
external tooling (Terp Studio) can visualize the full access graph without
importing ``terp.*`` — plus a human-readable text rendering. It is a **view,
never a second source of truth** (ADR 0011): nothing here configures anything.

Data-layer visibility requires the module to declare its services on the spec
(``ModuleSpec(services=(JournalService,))``). A module with a router but no
declared services is reported with an explicit warning ("data access not
visualizable"), fail-visible rather than silently incomplete.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from fastapi import FastAPI
from fastapi.routing import APIRoute
from starlette.routing import Mount, Route

from terp.core import (
    ActorStampedMixin,
    ControlPlane,
    ModuleSpec,
    OwnedMixin,
    SoftDeleteMixin,
)
from terp.core.object_authz import registered_object_authz_predicates
from terp.core.scoping import registered_scope_predicates

# Mirrors the kernel guard's method split (terp.core.app): any other method is a read.
_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Every module mounts under this prefix (``create_app``); a served path outside it is a
# kernel / open route (e.g. health), not part of any module's policy surface.
_API_PREFIX = "/api/v1/"

# OpenAPI path-item keys that are HTTP operations (the rest are metadata such as
# ``parameters`` / ``summary``) — used to read the served methods for each path.
_HTTP_METHODS = frozenset(
    {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
)

# The attribute the access capability stamps on a ``require_permission(...)``
# dependency so route-level grants are detectable here (a marker, not a control).
PERMISSION_DEPENDENCY_ATTR = "__terp_required_permission__"


def _policy_json(spec: ModuleSpec) -> dict[str, object] | None:
    """The module-access layer: the spec's declared ``Policy`` as plain data."""
    policy = spec.policy
    if policy is None:
        return None
    if policy.is_public:
        return {
            "public": True,
            "public_reason": policy.public_reason,
            "allows_public_writes": policy.allows_public_writes,
        }
    return {
        "public": False,
        "authenticated": policy.authenticated,
        "read": policy.read_requirement.label,
        "write": policy.write_requirement.label,
    }


def _route_permissions(route: APIRoute) -> list[str]:
    """Route-level ``require_permission`` names, where the dependency is marked."""
    found: list[str] = []
    for depends in route.dependencies:
        name = getattr(
            getattr(depends, "dependency", None), PERMISSION_DEPENDENCY_ATTR, None
        )
        if isinstance(name, str):
            found.append(name)
    return found


def _endpoint_json(spec: ModuleSpec, route: APIRoute) -> dict[str, object]:
    """The endpoint-access layer: one mounted route + its effective requirement."""
    methods = sorted(route.methods or ())
    is_write = any(method in _MUTATING_METHODS for method in methods)
    policy = spec.policy
    if policy is None:
        requirement = "denied (no policy declared)"
    elif policy.is_public:
        requirement = "public"
    else:
        requirement = (
            policy.write_requirement.label if is_write else policy.read_requirement.label
        )
    return {
        "path": f"/api/v1/{spec.name}{route.path}",
        "methods": methods,
        "kind": "write" if is_write else "read",
        "requirement": requirement,
        "extra_permissions": _route_permissions(route),
        "name": route.name,
    }


def _mro_names(model: type) -> set[str]:
    return {klass.__name__ for klass in model.__mro__}


def _model_json(service: type) -> dict[str, object] | None:
    """The data layer: one declared service's model + its enforced traits.

    Core traits are detected by ``issubclass``; the tenancy trait by MRO class
    name so this stays capability-agnostic (the CLI never imports
    ``terp.capabilities.tenancy``).
    """
    model = getattr(service, "model", None)
    if not isinstance(model, type):
        return None
    tenant_scoped = "TenantScopedMixin" in _mro_names(model)
    soft_delete = issubclass(model, SoftDeleteMixin)
    owned = issubclass(model, OwnedMixin)
    read_scope: list[str] = []
    if soft_delete:
        read_scope.append("soft-delete")
    if tenant_scoped:
        read_scope.append("tenant")
    write_authority: list[str] = []
    if owned:
        write_authority.append("owner")
    if tenant_scoped:
        write_authority.append("tenant-context")
    return {
        "model": model.__name__,
        "table": getattr(model, "__tablename__", None),
        "service": service.__name__,
        "traits": {
            "soft_delete": soft_delete,
            "owned": owned,
            "tenant_scoped": tenant_scoped,
            "actor_stamped": issubclass(model, ActorStampedMixin),
        },
        "read_scope": read_scope,
        "write_authority": write_authority,
    }


def _module_warnings(
    spec: ModuleSpec, models: Sequence[dict[str, object]]
) -> list[str]:
    """Honest gaps the Studio must not paper over (fail-visible, never silent)."""
    warnings: list[str] = []
    if spec.policy is None:
        warnings.append(
            "no Policy declared — create_app refuses to mount this module (deny-by-default)"
        )
    if spec.router is not None and not spec.services:
        warnings.append(
            "data access not visualizable: ModuleSpec declares no services — "
            "declare services=(YourService, ...) so the data layer appears here"
        )
    for model in models:
        traits = model["traits"]
        if traits["owned"]:  # type: ignore[index]
            warnings.append(
                f"{model['model']}: OwnedMixin gates writes only — reads are not "
                "owner-filtered unless a registered scope predicate narrows them"
            )
    return warnings


def _module_access_json(spec: ModuleSpec) -> dict[str, object]:
    endpoints: list[dict[str, object]] = []
    if spec.router is not None:
        endpoints = [
            _endpoint_json(spec, route)
            for route in spec.router.routes
            if isinstance(route, APIRoute)
        ]
        endpoints.sort(key=lambda item: (item["path"], item["methods"]))
    models = [
        entry
        for entry in (_model_json(service) for service in spec.services)
        if entry is not None
    ]
    return {
        "name": spec.name,
        "prefix": f"/api/v1/{spec.name}" if spec.router is not None else None,
        "policy": _policy_json(spec),
        "endpoints": endpoints,
        "models": models,
        "warnings": _module_warnings(spec, models),
    }


def build_access_graph(
    plane: ControlPlane,
    specs: Sequence[ModuleSpec],
    *,
    kernel_routes: Sequence[dict[str, object]] = (),
    omitted_routes: Sequence[dict[str, object]] = (),
    undeclared_subscribers: Sequence[dict[str, object]] = (),
) -> dict[str, object]:
    """The Access Graph as plain data: roles -> modules -> endpoints -> data traits.

    The stable contract ``terp inspect access --format json`` emits for Studio
    and other external tooling. App-wide registered predicates are reported by
    (qualified) name so a custom row-visibility or object-authz policy is
    *visible* in the graph even though its logic lives in code.

    ``kernel_routes`` (unauthenticated framework routes, e.g. health) and
    ``omitted_routes`` (mounted routes the graph does not cover — a leak alarm)
    are supplied by :func:`build_access_graph_for_app`, which reconciles the graph
    against the composed app; both are empty for a hand-passed module list.
    """
    return {
        "roles": [
            {"name": role.name, "rank": role.rank}
            for role in sorted(plane.permissions.roles, key=lambda item: item.rank)
        ],
        "permissions": [
            {"name": permission.name, "min_role": permission.min_role.name}
            for permission in sorted(
                plane.permissions.permissions, key=lambda item: item.name
            )
        ],
        "modules": [
            _module_access_json(spec) for spec in sorted(specs, key=lambda s: s.name)
        ],
        "scope_predicates": [
            f"{predicate.__module__}.{predicate.__qualname__}"
            for predicate in registered_scope_predicates()
        ],
        "object_authz_predicates": [
            f"{predicate.__module__}.{predicate.__qualname__}"
            for predicate in registered_object_authz_predicates()
        ],
        "kernel_routes": list(kernel_routes),
        "omitted_routes": list(omitted_routes),
        "undeclared_subscribers": list(undeclared_subscribers),
    }


def _undeclared_subscriber_alarms(specs: Sequence[ModuleSpec]) -> list[dict[str, object]]:
    """Registered event handlers no module declares subscribing to (drift alarm).

    The eventbus registry holds the ACTUAL handlers; ``ModuleSpec.subscribes`` is the
    declared contract the control-plane view shows. A handler for an event nobody
    declares is executable code reacting to events invisibly — alarmed, never dropped.
    Lazy: an app without the eventbus capability has no registry (empty alarms).
    """
    try:
        from terp.capabilities.eventbus.registry import registered_handlers
    except ImportError:  # pragma: no cover - eventbus not installed
        return []
    declared = {
        event.name for spec in specs for event in spec.subscribes
    }
    return [
        {
            "event": name,
            "handlers": [
                f"{handler.__module__}.{handler.__qualname__}" for handler in handlers
            ],
            "detail": "registered handler(s) for an event NO module declares "
            "subscribing to (ModuleSpec.subscribes) -- invisible drift",
        }
        for name, handlers in sorted(registered_handlers().items())
        if name not in declared
    ]


def _served_routes(app: FastAPI) -> dict[str, frozenset[str]]:
    """Every path the composed app serves -> its HTTP methods, from ``app.openapi()``.

    ``app.openapi()`` is the same document ``terp openapi`` exports and FastAPI serves,
    so it is the authoritative, full-path route table — client module routers, every
    discovered capability router, and the kernel health routes — the ground truth the
    access graph is reconciled against.
    """
    paths: dict[str, object] = app.openapi().get("paths", {})
    return {
        path: frozenset(
            method.upper() for method in item if method.lower() in _HTTP_METHODS
        )
        for path, item in paths.items()
    }


def _schema_hidden_routes(app: FastAPI) -> list[dict[str, object]]:
    """Reachable top-level routes ``app.openapi()`` does NOT list — still reported.

    FastAPI's own docs/schema endpoints (``/openapi.json`` / ``/docs`` / ``/redoc``,
    plain starlette ``Route``s with ``include_in_schema=False``) and any ``app.mount()``
    sub-application are reachable surface: a complete permission audit must show them,
    so they join ``kernel_routes`` instead of hiding outside the OpenAPI ground truth.
    """
    hidden: list[dict[str, object]] = []
    for route in app.routes:
        if isinstance(route, APIRoute):
            continue  # schema-visible; reconciled via app.openapi()
        if isinstance(route, Mount):
            hidden.append(
                {
                    "path": f"{route.path}/*",
                    "methods": ["*"],
                    "note": "mounted sub-application — its own routes are not "
                    "policy-guarded by any ModuleSpec",
                }
            )
        elif isinstance(route, Route) and not route.include_in_schema:
            hidden.append(
                {
                    "path": route.path,
                    "methods": sorted(route.methods or ()),
                    "note": "framework route outside the OpenAPI schema (docs/schema)",
                }
            )
    return hidden


def build_access_graph_for_app(app: FastAPI) -> dict[str, object]:
    """The access graph for a fully composed app — the WHOLE guarded surface.

    ``create_app`` records the specs it mounted (client modules AND every discovered
    capability router) and its control plane on ``app.state``; this reads them back so
    the graph covers routes a hand-passed ``--module`` list would miss. It then
    reconciles the graph against ``app.openapi()`` (the ground truth): every served
    ``/api/v1`` method must map to a module endpoint — any that does not is reported
    under ``omitted_routes`` (fail-visible, so a mounted route can never hide) — and the
    served routes outside ``/api/v1`` (the unauthenticated kernel health routes), the
    schema-hidden framework routes (``/docs`` / ``/openapi.json`` / ``/redoc``), and any
    ``app.mount()`` sub-application are listed under ``kernel_routes``.
    """
    specs = getattr(app.state, "terp_module_specs", None)
    plane = getattr(app.state, "terp_control_plane", None)
    if specs is None or plane is None:
        raise ValueError(
            "app was not composed by terp.core.create_app (no access-graph state on "
            "app.state) — pass a terp app factory, e.g. --app app.main:build"
        )
    served = _served_routes(app)
    kernel_routes: list[dict[str, object]] = [
        {
            "path": path,
            "methods": sorted(methods),
            "note": "unauthenticated kernel route (no module policy)",
        }
        for path, methods in sorted(served.items())
        if not path.startswith(_API_PREFIX)
    ]
    kernel_routes.extend(_schema_hidden_routes(app))
    graph = build_access_graph(
        plane,
        specs,
        kernel_routes=kernel_routes,
        undeclared_subscribers=_undeclared_subscriber_alarms(specs),
    )
    covered: dict[str, set[str]] = {}
    modules: list = graph["modules"]  # type: ignore[assignment]
    for module in modules:
        for endpoint in module["endpoints"]:
            covered.setdefault(endpoint["path"], set()).update(endpoint["methods"])
    omitted: list[dict[str, object]] = []
    for path, methods in sorted(served.items()):
        if not path.startswith(_API_PREFIX):
            continue
        missing = sorted(methods - covered.get(path, set()))
        if missing:
            omitted.append({"path": path, "methods": missing})
    graph["omitted_routes"] = omitted
    return graph


def _render_access_text(graph: dict[str, object]) -> str:
    lines = ["Access graph", "", "Roles"]
    for role in graph["roles"]:  # type: ignore[index, union-attr]
        lines.append(f"  {role['name']} ({role['rank']})")
    lines.append("")
    lines.append("Permissions")
    permissions = graph["permissions"]  # type: ignore[index]
    if not permissions:
        lines.append("  <none declared>")
    for permission in permissions:  # type: ignore[union-attr]
        lines.append(f"  {permission['name']}  {permission['min_role']}+")
    for module in graph["modules"]:  # type: ignore[index, union-attr]
        lines.append("")
        prefix = module["prefix"] or "<no router>"
        lines.append(f"Module {module['name']}  ({prefix})")
        policy = module["policy"]
        if policy is None:
            lines.append("  policy <missing> (boot refuses this module)")
        elif policy["public"]:
            lines.append(f"  policy public ({policy['public_reason']})")
        else:
            lines.append(f"  policy read={policy['read']}  write={policy['write']}")
        for endpoint in module["endpoints"]:
            extra = (
                f"  +permissions: {', '.join(endpoint['extra_permissions'])}"
                if endpoint["extra_permissions"]
                else ""
            )
            lines.append(
                f"  {','.join(endpoint['methods']):8} {endpoint['path']:40} "
                f"{endpoint['kind']:5} {endpoint['requirement']}{extra}"
            )
        for model in module["models"]:
            read_scope = ", ".join(model["read_scope"]) or "none"
            write_authority = ", ".join(model["write_authority"]) or "role tier only"
            lines.append(
                f"  data {model['model']} ({model['table']})  "
                f"read-scope: {read_scope}  write-authority: {write_authority}"
            )
        for warning in module["warnings"]:
            lines.append(f"  ! {warning}")
    lines.append("")
    lines.append("Row-scope predicates (app-wide)")
    scope_predicates = graph["scope_predicates"]  # type: ignore[index]
    if not scope_predicates:
        lines.append("  <none registered>")
    for name in scope_predicates:  # type: ignore[union-attr]
        lines.append(f"  {name}")
    lines.append("Object-authz predicates (app-wide)")
    authz_predicates = graph["object_authz_predicates"]  # type: ignore[index]
    if not authz_predicates:
        lines.append("  <none registered>")
    for name in authz_predicates:  # type: ignore[union-attr]
        lines.append(f"  {name}")
    kernel_routes: list = graph.get("kernel_routes", [])  # type: ignore[assignment]
    if kernel_routes:
        lines.append("")
        lines.append("Kernel / unauthenticated routes")
        for route in kernel_routes:
            lines.append(f"  {','.join(route['methods']):8} {route['path']}")
    omitted: list = graph.get("omitted_routes", [])  # type: ignore[assignment]
    if omitted:
        lines.append("")
        lines.append("! OMITTED served routes — mounted but absent from the graph:")
        for route in omitted:
            lines.append(f"  {','.join(route['methods']):8} {route['path']}")
    undeclared: list = graph.get("undeclared_subscribers", [])  # type: ignore[assignment]
    if undeclared:
        lines.append("")
        lines.append("! UNDECLARED event subscribers — handlers no module declares:")
        for entry in undeclared:
            lines.append(f"  {entry['event']}: {', '.join(entry['handlers'])}")
    return "\n".join(lines)


def render_access_graph(graph: dict[str, object], fmt: str = "text") -> str:
    """Render a prebuilt access *graph* as ``text`` or ``json``."""
    if fmt == "json":
        return json.dumps(graph, indent=2)
    return _render_access_text(graph)


def render_access(
    plane: ControlPlane, specs: Sequence[ModuleSpec], fmt: str = "text"
) -> str:
    """Render the access graph for *plane* + *specs* as ``text`` or ``json``."""
    return render_access_graph(build_access_graph(plane, specs), fmt)


__all__ = [
    "PERMISSION_DEPENDENCY_ATTR",
    "build_access_graph",
    "build_access_graph_for_app",
    "render_access",
    "render_access_graph",
]
