"""``authz-surface`` — the authority baseline, and the drift check that pins it.

The access graph already replays enforcement rather than describing it: every allowance
in it is :func:`terp.core.module_spec.decide`'s own answer, computed by the same function
the kernel guard runs (ADR 0121 §4). So the platform can already *say* who may reach
what, exactly and truthfully, for any composed app.

What nothing did was **notice when that answer changed**. Widening a module's policy from
a named permission to a role tier, dropping a ``require_permission`` off a route, adding
an endpoint under a mount whose policy is public — each is a one-line edit, each changes
who can reach what, and each left every gate green. The projection was emitted for a pane
and for a CLI, and read by no check.

This is the check. It reduces the graph to the part that is an authority claim, compares
it against a committed baseline, and reports the difference in the vocabulary of the
change rather than as a JSON diff: *this route's requirement moved from X to Y*, *this
module became public*, *this endpoint is new and nothing has reviewed what it requires*.

**Adoption is opt-in and half-adoption is impossible**, the shape ``api-docs-drift``
settled on: with no committed baseline the check skips with a note naming the command
that writes one, because upgrading the framework must not turn an app's gate red for a
feature it never wired. Once the file is tracked, drift is red.

**A widening is never "fixed" by regenerating.** The baseline is a review artifact: the
diff belongs in a pull request where somebody looks at it and says yes. Regenerating to
make a red go away converts the control into a formality, which is why the writer is a
separate, explicit command and never a ``--fix`` on the checker.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

#: The committed baseline, at the project root beside the other tracked artifacts.
SURFACE_ARTIFACT = "authz-surface.json"

#: What an app runs once to adopt the check, and again — deliberately, with the diff in
#: front of a reviewer — to accept a change.
ADOPT_HINT = "terp inspect access --app app.main:build --format surface > authz-surface.json"


def authz_surface(graph: dict[str, Any]) -> dict[str, Any]:
    """Reduce an access graph to the part that is an authority claim.

    Deliberately **not** the whole graph. The graph carries things that move for honest
    reasons — a model's traits, the reconciliation's ``omitted_routes``, whatever a
    future field adds — and a baseline that churned on those would be regenerated
    reflexively until nobody read the diff. What survives here is what answers "who may
    reach what": the role ladder, each permission's floor, and per module its policy plus
    each endpoint's requirement, extra permissions, and per-rung outcome.

    Sorted at every level, because the baseline is a **diffable** artifact: a set
    rendered in registration order would produce a reviewable diff only by luck.
    """
    roles = [
        {"name": role["name"], "rank": role["rank"]}
        for role in sorted(graph.get("roles", ()), key=lambda item: item["rank"])
    ]
    permissions = [
        {"name": permission["name"], "min_role": permission["min_role"]}
        for permission in sorted(
            graph.get("permissions", ()), key=lambda item: item["name"]
        )
    ]
    modules = [
        {
            "name": module["name"],
            "policy": module.get("policy"),
            "access": module.get("access"),
            "endpoints": [
                {
                    "path": endpoint["path"],
                    "methods": sorted(endpoint.get("methods", ())),
                    "requirement": endpoint["requirement"],
                    "extra_permissions": sorted(endpoint.get("extra_permissions", ())),
                    "by_role": {
                        rung["role"]: rung["reason"]
                        for rung in endpoint.get("by_role", ())
                    },
                }
                for endpoint in sorted(
                    module.get("endpoints", ()),
                    key=lambda item: (item["path"], sorted(item.get("methods", ()))),
                )
            ],
        }
        for module in sorted(graph.get("modules", ()), key=lambda item: item["name"])
    ]
    return {"authz_surface": 1, "roles": roles, "permissions": permissions, "modules": modules}


def render_authz_surface(graph: dict[str, Any]) -> str:
    """The baseline as the bytes a project commits (trailing newline, stable key order)."""
    return json.dumps(authz_surface(graph), indent=2, sort_keys=True) + "\n"


def _endpoints(surface: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    """Every endpoint keyed by ``(path, methods)`` — the identity a diff compares on."""
    found: dict[tuple[str, str], dict[str, Any]] = {}
    for module in surface.get("modules", ()):
        for endpoint in module.get("endpoints", ()):
            key = (endpoint["path"], ",".join(endpoint.get("methods", ())) or "WS")
            found[key] = endpoint
    return found


def diff_authz_surface(baseline: dict[str, Any], current: dict[str, Any]) -> list[str]:
    """Every authority difference, each phrased as the change a reviewer has to approve.

    Ordered most-alarming first — a route that lost its requirement before one that
    gained a new rung — because the first lines are the ones that get read.
    """
    differences: list[str] = []

    before, after = _endpoints(baseline), _endpoints(current)
    for key in sorted(before.keys() & after.keys()):
        was, now = before[key], after[key]
        path, methods = key
        if was["requirement"] != now["requirement"]:
            differences.append(
                f"{methods} {path}: requirement {was['requirement']!r} -> "
                f"{now['requirement']!r}"
            )
        if was.get("extra_permissions") != now.get("extra_permissions"):
            differences.append(
                f"{methods} {path}: required grants "
                f"{was.get('extra_permissions')} -> {now.get('extra_permissions')}"
            )
        widened = [
            role
            for role, reason in now.get("by_role", {}).items()
            if reason in {"allowed", "allowed_in_module", "public"}
            and was.get("by_role", {}).get(role)
            not in {"allowed", "allowed_in_module", "public"}
        ]
        if widened:
            differences.append(
                f"{methods} {path}: now reachable by {sorted(widened)} "
                "(it was not before)"
            )

    for key in sorted(after.keys() - before.keys()):
        path, methods = key
        differences.append(
            f"{methods} {path}: NEW endpoint, requirement "
            f"{after[key]['requirement']!r} - nothing has reviewed what it requires"
        )
    for key in sorted(before.keys() - after.keys()):
        path, methods = key
        differences.append(f"{methods} {path}: gone from the surface")

    # A module's own policy and access. The endpoint lines above test one method per route,
    # so a route serving GET and POST can have its read tier lowered with no endpoint line
    # moving; and a module that starts taking per-module roles lets an assignment lift a
    # caller over a floor (ADR 0121) without any rung's answer changing in this view.
    before_modules = {module["name"]: module for module in baseline.get("modules", ())}
    after_modules = {module["name"]: module for module in current.get("modules", ())}
    for name in sorted(before_modules.keys() & after_modules.keys()):
        was, now = before_modules[name], after_modules[name]
        for field in ("policy", "access"):
            if was.get(field) != now.get(field):
                differences.append(
                    f"module {name}: {field} {was.get(field)!r} -> {now.get(field)!r}"
                )

    # The ladder itself, last: a changed rank silently re-scores every floor above it.
    if baseline.get("roles") != current.get("roles"):
        differences.append(
            f"the role ladder changed: {baseline.get('roles')} -> {current.get('roles')}"
        )
    if baseline.get("permissions") != current.get("permissions"):
        differences.append("the declared permissions or their floors changed")

    # Anything the lines above do not name is still a change to who can reach what, or
    # to the record of it. Passing it as "no difference" is the one answer this check
    # must never give, so it is reported whole rather than itemised.
    if not differences and baseline != current:
        differences.append(
            "the authorization surface changed in a way this check does not itemise; "
            f"read the diff of {SURFACE_ARTIFACT} line by line"
        )
    return differences


def served_twice(surface: dict[str, Any]) -> list[str]:
    """Every method and path that more than one route serves.

    The router answers with the first route registered, while a diff keyed by method and
    path compares whichever it met last, so a second route under an existing path can
    serve a different policy with no line moving. The surface cannot say which route
    answers, so each such pair is reported rather than resolved.
    """
    seen: dict[tuple[str, str], int] = {}
    for module in surface.get("modules", ()):
        for endpoint in module.get("endpoints", ()):
            for method in endpoint.get("methods") or ["WS"]:
                key = (method, endpoint["path"])
                seen[key] = seen.get(key, 0) + 1
    return [
        f"{method} {path}: served by {count} routes; the first one registered answers, "
        "and this check cannot say which that is"
        for (method, path), count in sorted(seen.items())
        if count > 1
    ]


def read_baseline(root: pathlib.Path) -> dict[str, Any] | None:
    """The committed baseline, or ``None`` when the project has not adopted the check."""
    path = root / SURFACE_ARTIFACT
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))

def check(project_root: pathlib.Path, app_ref: str, *, note_prefix: str) -> tuple[int, str]:
    """The ``authz-surface`` verify check over one tree: ``(exit code, output)``.

    The access graph already replays enforcement — every allowance in it is `decide`'s
    own answer, from the function the kernel guard runs — so the platform could always
    *say* who may reach what. What nothing did was notice when the answer changed.
    Widening a module policy from a named permission to a role tier, dropping a
    `require_permission`, adding an endpoint under a public mount: each is a one-line
    edit that changes the authorization surface and left every gate green.

    Adoption is opt-in and half-adoption impossible, the shape `api-docs-drift` settled
    on: with no committed baseline this skips with a note naming the command that writes
    one, because upgrading the framework must not turn an app's gate red for a feature
    it never wired.

    A widening is never *fixed* by regenerating. The baseline is a review artifact, and
    the diff belongs in a pull request where somebody says yes — which is why the writer
    is a separate, explicit command and never a `--fix` on this.

    Once a tree pins its surface, what the check cannot see is red, never a pass: an app
    that cannot be composed, a route the access graph cannot place, a method and path two
    routes serve, and a difference no line of the diff names.
    """
    from terp.cli._appref import load_app, push_app_root
    from terp.cli.access import build_access_graph_for_app

    baseline = read_baseline(project_root)
    if baseline is None:
        return (
            0,
            f"{note_prefix}no {SURFACE_ARTIFACT} - the authorization surface is not "
            f"pinned, drift check skipped (adopt with: {ADOPT_HINT})",
        )
    push_app_root(project_root)
    try:
        app = load_app(app_ref)
    except (SystemExit, ImportError) as exc:
        # The tree pins its surface, so an app that cannot be composed is an unchecked
        # surface, not an absent one. Skipping here passed every change for as long as
        # the app failed to import, which is the one moment nobody is looking.
        return 1, (
            f"{SURFACE_ARTIFACT} pins this app's authorization surface, but {app_ref} "
            f"could not be composed ({exc}), so nothing was checked. Make the app "
            "importable, or remove the baseline in a change a reviewer sees."
        )
    graph = build_access_graph_for_app(app)
    current = authz_surface(graph)
    # What the surface cannot see is refused before it is compared: a route the graph
    # could not place (a router included inside a module's router, served under a path
    # the graph cannot recover) and a method and path two routes serve. Either one makes
    # "no difference" an answer about a surface that is not the one being served.
    unseen = [
        f"{','.join(route.get('methods') or ['WS'])} {route['path']}: served, but the "
        "access graph cannot place it (a router included inside a module's router); "
        "declare it on the module's own router"
        for route in graph.get("omitted_routes") or ()
    ] + served_twice(current)
    if unseen:
        listing = "\n".join(f"  - {line}" for line in unseen)
        return 1, (
            f"the authorization surface cannot be checked: {len(unseen)} route(s) are "
            f"served in a way {SURFACE_ARTIFACT} cannot record:\n{listing}"
        )
    differences = diff_authz_surface(baseline, current)
    if not differences:
        return 0, f"{SURFACE_ARTIFACT} matches the composed authorization surface"
    listing = "\n".join(f"  - {difference}" for difference in differences)
    return 1, (
        f"the authorization surface changed in {len(differences)} way(s) that "
        f"{SURFACE_ARTIFACT} does not record:\n{listing}\n\n"
        "If every line above is intended, re-generate the baseline IN THE SAME CHANGE "
        f"so a reviewer sees the diff:\n  {ADOPT_HINT}"
    )
