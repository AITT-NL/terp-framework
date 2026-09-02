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

from fastapi.routing import APIRoute

from terp.core.control_plane import ControlPlane
from terp.core.module_spec import ModuleSpec, Policy, Role, decide
from terp.core.routing import MUTATING_METHODS, declared_operation, required_permission

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


def route_permissions(route: APIRoute) -> list[str]:
    """Route-level ``require_permission`` names, where the dependency is marked.

    The marker is stamped by the access capability and named in ``terp.core.routing`` — read
    through that module's accessor rather than by knowing the attribute name here.
    """
    found: list[str] = []
    for depends in route.dependencies:
        name = required_permission(getattr(depends, "dependency", None))
        if name is not None:
            found.append(name)
    return found


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
    """
    outcome = decide(policy, method=probe, role=role)
    if outcome.allowed and extra_permissions and outcome.reason != "public":
        return {"role": role.name, "allowed": False, "reason": "grant"}
    return {"role": role.name, "allowed": outcome.allowed, "reason": outcome.reason}


def endpoint_json(
    spec: ModuleSpec, route: APIRoute, ladder: Sequence[Role] = ()
) -> dict[str, object]:
    """The endpoint-access layer: one mounted route + its effective requirement.

    No read/write field is emitted. One used to be, computed from the HTTP method alone,
    which meant it restated the ``methods`` beside it and carried no authority of its own —
    and it invited a false reading, because a module may require the same tier for both (the
    boot check permits exactly that, and the files capability does it), so "read" never meant
    "cannot write". ``requirement`` is the honest field: the requirement the guard has
    already chosen for this method.
    """
    methods = sorted(route.methods or ())
    is_write = any(method in MUTATING_METHODS for method in methods)
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
    declared = declared_operation(route.endpoint)
    extra_permissions = route_permissions(route)
    return {
        "path": f"/api/v1/{spec.name}{route.path}",
        "methods": methods,
        "requirement": requirement,
        "extra_permissions": extra_permissions,
        "name": route.name,
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
        endpoints = [
            endpoint_json(spec, route, ladder)
            for route in spec.router.routes
            if isinstance(route, APIRoute)
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
                "summary": spec.access.summary or None,
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
    ladder = tuple(sorted(plane.permissions.roles, key=lambda item: item.rank))
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


__all__ = [
    "build_access_model",
    "endpoint_json",
    "module_json",
    "policy_json",
    "route_permissions",
]
