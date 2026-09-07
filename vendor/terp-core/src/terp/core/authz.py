"""The declared authority surface as plain data — one projection, several consumers.

This is the shared half of what ``terp inspect access`` has always produced, moved into the
kernel because it grew a second consumer. The CLI reads it to render an audit view; the
access capability serves it over HTTP so an app's own admin pane can render a permission
matrix; the Studio reads the CLI's JSON at design time. A capability cannot import
``terp.cli`` — the tool sits above it — so the alternative to moving it was a second
projection, which is the thing ADR 0112 §4 exists to prevent.

What stays in the CLI is what only an audit needs: model traits, registered predicates,
kernel and schema-hidden routes, undeclared event subscribers, and the reconciliation of the
graph against ``app.openapi()`` that reports a mounted route the graph does not cover. Those
answer "is anything hiding?", which is a different question from "who may do what", and they
have exactly one consumer.

Every allowance here is computed by :func:`terp.core.module_spec.decide` — the same function
the kernel guard runs — so a view replays enforcement rather than describing it.
"""

from __future__ import annotations

from collections.abc import Sequence

from fastapi.routing import APIRoute, APIWebSocketRoute

from terp.core.control_plane import ControlPlane
from terp.core.module_spec import ModuleSpec, Policy, Role, decide
from terp.core.routing import (
    MUTATING_METHODS,
    declared_operation,
    route_permission_names,
)

# A role below every rank a real ladder can hold, used only to read *which* requirement a
# policy applies to a method. ``decide`` returns the applied requirement even when it denies
# at the floor, so probing with a rank nothing can be declared at yields the requirement
# without this module re-deriving the read-or-write choice the guard already makes. It is
# never reported and never compared against a real principal.
_FLOOR_PROBE = Role("floor_probe", rank=-1)


def policy_json(spec: ModuleSpec) -> dict[str, object] | None:
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


def route_permissions(route: object) -> list[str]:
    """Every ``require_permission`` name this route enforces.

    Delegates to :func:`terp.core.routing.route_permission_names`, which walks the resolved
    dependency tree so a marker declared in the endpoint *signature* counts too. Reading
    ``route.dependencies`` here missed exactly that form, and the route's rungs were then
    reported as plainly ``allowed`` while an ungranted caller got a 403.
    """
    return route_permission_names(route)


def _by_role_json(
    role: Role,
    policy: Policy | None,
    probe: str,
    extra_permissions: Sequence[str],
) -> dict[str, object]:
    """One rung's outcome on one route — the module guard *and* the route's own dependency.

    :func:`~terp.core.module_spec.decide` answers for the module ``Policy``, which is the
    only authority the kernel guard applies. A route-level ``require_permission`` is a
    **second** requirement, added by the access capability on top, and the ``Policy`` does
    not carry it — so replaying only the guard reported an editor as allowed on a route an
    editor without the grant gets a 403 from. That is the exact class of disagreement between
    a pane and the gate that ADR 0112 exists to prevent, so the extra requirement is folded
    in here.

    A view has no subject, so it cannot know whether the grant is held: a rung that clears
    the policy but faces a route-level permission is reported ``grant``, on the same terms
    ``decide`` reports a permission requirement it was given no check for.

    **A public policy is folded too**, and the exclusion that used to be here was a defect. A
    ``Policy.public_write`` route carrying ``require_permission`` is the documented way to gate
    an action on a grant rather than a tier — the example app's own fixture says so in its
    justification — and for it the module guard admits everyone while the route-level
    dependency still answers 401 unauthenticated and 403 ungranted. Reporting those rungs as
    ``allowed`` was the pane disagreeing with the gate in the one function written to stop
    that.
    """
    outcome = decide(policy, method=probe, role=role)
    if outcome.allowed and extra_permissions:
        return {"role": role.name, "allowed": False, "reason": "grant"}
    return {"role": role.name, "allowed": outcome.allowed, "reason": outcome.reason}


def endpoint_json(
    spec: ModuleSpec, route: object, ladder: Sequence[Role] = ()
) -> dict[str, object]:
    """The endpoint-access layer: one mounted route + its effective requirement.

    No read/write field is emitted. One used to be, computed from the HTTP method alone,
    which meant it restated the ``methods`` beside it and carried no authority of its own —
    and it invited a false reading, because a module may require the same tier for both (the
    boot check permits exactly that, and the files capability does it), so "read" never meant
    "cannot write". ``requirement`` is the honest field: the requirement the guard has
    already chosen for this method.
    """
    # A WebSocket route carries no `methods` at all, and the guard treats it as a write —
    # `request_method` says so in as many words, because there is no HTTP method after the
    # upgrade. Matching that here is what keeps the projection a replay: reading `.methods`
    # directly used to be safe only because this walk skipped every non-`APIRoute`, so
    # descending into nested routers turned a silent omission into an AttributeError.
    methods = sorted(getattr(route, "methods", None) or ())
    is_write = not methods or any(method in MUTATING_METHODS for method in methods)
    # One representative method, so `decide` makes the read-or-write choice rather than this
    # projection making it again. That second copy is what ADR 0112 §4 removed: the guard and
    # this function each tested the method against MUTATING_METHODS, and the copy that drifts
    # is the one an administrator is shown.
    probe = "POST" if is_write else "GET"
    policy = spec.policy
    if policy is None:
        requirement = "denied (no policy declared)"
    elif policy.is_public:
        requirement = "public"
    else:
        applied = decide(policy, method=probe, role=_FLOOR_PROBE).requirement
        requirement = "denied (no policy declared)" if applied is None else applied.label
    declared = declared_operation(getattr(route, "endpoint", None))
    extra_permissions = route_permissions(route)
    return {
        "path": f"/api/v1/{spec.name}{getattr(route, 'path', '')}",
        # Empty for a WebSocket, which is the honest answer: it has no HTTP method after the
        # upgrade. A view renders that as the WS surface it is rather than inventing a verb.
        "methods": methods,
        "requirement": requirement,
        "extra_permissions": extra_permissions,
        "name": getattr(route, "name", ""),
        # The declared operation (ADR 0102), or null where the route declares none. A view
        # that renders "what this endpoint does" needs the authored answer when there is one
        # and must fall back to the route name when there is not, so the absence is reported
        # as null rather than omitted — a missing key and a declined declaration would
        # otherwise be indistinguishable.
        "operation": (
            None if declared is None else {"id": declared.id, "label": declared.label}
        ),
        # What each declared rung gets on this route, replayed through the guard's own
        # decision rather than re-derived from ranks by whatever renders the matrix. A view
        # has no subject, so a permission requirement comes back as ``grant`` — "clears the
        # floor, still needs the named grant" — which is the distinction a cell has to draw
        # and the one a client-side rank comparison cannot.
        "by_role": [
            _by_role_json(role, spec.policy, probe, extra_permissions) for role in ladder
        ],
    }


def module_json(spec: ModuleSpec, ladder: Sequence[Role] = ()) -> dict[str, object]:
    """One module's declared authority: its policy, its permissions, and its routes."""
    endpoints: list[dict[str, object]] = []
    if spec.router is not None:
        # Top-level routes only, and a WebSocket route counts — it is guarded by the same
        # module policy and was previously dropped by an `isinstance(route, APIRoute)` filter.
        #
        # NOT a descent into included sub-routers, and that is deliberate rather than an
        # oversight. `APIRouter.include_router` keeps the child as an `_IncludedRouter` whose
        # wrapper carries no prefix, so a walk can recover the child's routes but not the paths
        # they are actually served under: descending reported `/api/v1/widgets/nested` for a
        # route served at `/api/v1/widgets/deep/nested`. A permission view naming a path that
        # does not exist is worse than one that omits it, so the coverage guarantee stays where
        # it can be made truthfully — `build_access_graph_for_app` reconciles against
        # `app.openapi()` and reports any uncovered served route under `omitted_routes`, which
        # is the alarm `test_access_graph_flags_nested_router_routes_instead_of_dropping_them`
        # pins. See §4.9 of the plan for the residual gap on `GET /model`, which has no such
        # reconciliation yet.
        endpoints = [
            endpoint_json(spec, route, ladder)
            for route in spec.router.routes
            if isinstance(route, APIRoute | APIWebSocketRoute)
        ]
        endpoints.sort(key=lambda item: (item["path"], item["methods"]))
    return {
        "name": spec.name,
        "prefix": f"/api/v1/{spec.name}" if spec.router is not None else None,
        "policy": policy_json(spec),
        # The permissions this module claims (``ModuleSpec.permissions``), by name. The
        # module edge is what lets a permission editor render one row per module instead of
        # inferring ownership from a dotted prefix; the names resolve against the model's
        # top-level ``permissions`` list, which carries each floor and label.
        "permissions": sorted(permission.name for permission in spec.permissions),
        # Whether this module takes part in per-module role assignment, and what it is
        # called (ADR 0112). ``null`` where the module has not declared — which is the
        # secure default, not a gap: absence means global rank only, as before.
        "access": (
            None
            if spec.access is None
            else {
                "assignable": spec.access.assignable,
                "label": spec.access.label or None,
                "platform_reason": spec.access.platform_reason,
            }
        ),
        "endpoints": endpoints,
    }


def build_access_model(
    plane: ControlPlane, specs: Sequence[ModuleSpec]
) -> dict[str, object]:
    """The declared authority surface: the ladder, the permissions, and every module.

    Pure derivation over declarations — no database read, so it is the same for every caller
    for the lifetime of a boot. It is a **view, never a second source of truth** (ADR 0011):
    nothing here configures anything, and every allowance is ``decide``'s answer rather than
    this module's opinion of it.
    """
    ladder = tuple(plane.permissions.roles)
    return {
        "roles": [{"name": role.name, "rank": role.rank} for role in ladder],
        "permissions": [
            {
                "name": permission.name,
                "min_role": permission.min_role.name,
                # What holding it buys, in the source language, or null where the app has
                # not said. Reported as null rather than omitted for the same reason a
                # route's declined operation is: a missing key and an undeclared label
                # would otherwise be indistinguishable to a viewer.
                "label": permission.label or None,
            }
            for permission in sorted(
                plane.permissions.permissions, key=lambda item: item.name
            )
        ],
        "modules": [
            module_json(spec, ladder) for spec in sorted(specs, key=lambda s: s.name)
        ],
    }


# Only the builder. `endpoint_json`, `module_json`, `policy_json` and `route_permissions` were
# exported alongside it and consumed by nothing outside this module — "name the consumer or drop
# it" applies to a helper that merely looks reusable. They stay module-level functions, so the
# CLI's composition can still call one the day it needs to.
__all__ = ["build_access_model"]
