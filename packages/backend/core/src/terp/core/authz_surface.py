"""The authorization surface: who may reach what, as one record, and the app's own check of it.

The access model already replays enforcement rather than describing it: every allowance in
it is :func:`terp.core.module_spec.decide`'s own answer, computed by the same function the
kernel guard runs (ADR 0121). This module reduces that model to the part that is an
authority claim, and two halves read it (ADR 0212):

**The check before release** (``terp verify --only authz-surface``, ADR 0139 and 0209)
composes the app and compares the reduction with the committed ``authz-surface.json``.

**The app, when it starts.** That check judges an app by running it, so code written to fool
it can show the check a narrower app than the one it serves: notice that it is being
inspected, and leave a route out only then. So ``create_app`` reduces the routes it just
composed with the same function and compares them with the same record, shipped beside the
app. Outside ``ENVIRONMENT=local`` any difference is a boot error, and the app does not serve.

One reduction for both, on purpose: a second one would be a second answer to "what does this
app serve", one that a reviewer approved and one that the app held itself to.
"""

from __future__ import annotations

import json
import logging
import pathlib
from collections.abc import Mapping, Sequence
from typing import Any

from fastapi import FastAPI
from fastapi.routing import APIRoute, APIWebSocketRoute, iter_route_contexts
from starlette.routing import Mount, WebSocketRoute

from terp.core.authz import build_access_model
from terp.core.authz_changes import authority_changes
from terp.core.control_plane import ControlPlane
from terp.core.module_spec import ModuleSpec

_logger = logging.getLogger("terp.core")

#: The committed record, at the project root beside the other tracked artifacts, and in the
#: working directory of the image the deployment generator writes.
SURFACE_ARTIFACT = "authz-surface.json"

#: What an app runs once to adopt the check, and again, deliberately and with the diff in
#: front of a reviewer, to accept a change.
ADOPT_HINT = "terp inspect access --app app.main:build --format surface > authz-surface.json"

#: Every module mounts under this prefix (``create_app``); a served path outside it is a
#: kernel route (health and its like), not part of any module's policy surface.
API_PREFIX = "/api/v1/"

#: What a served WebSocket route is listed under: it has no HTTP method after the upgrade.
WEBSOCKET = "WS"

#: How many differences a startup refusal names before it counts the rest. The whole list
#: is the check's to give; a boot error is read in a log.
_NAMED = 5


def authz_surface(graph: Mapping[str, Any]) -> dict[str, Any]:
    """Reduce an access model or graph to the part that is an authority claim.

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


def render_authz_surface(graph: Mapping[str, Any]) -> str:
    """The baseline as the bytes a project commits (trailing newline, stable key order)."""
    return json.dumps(authz_surface(graph), indent=2, sort_keys=True) + "\n"


def served_twice(surface: Mapping[str, Any]) -> list[str]:
    """Every method and path that more than one route serves.

    The router answers with the first route registered, while a diff keyed by method and
    path compares whichever it met last, so a second route under an existing path can
    serve a different policy with no line moving. The surface cannot say which route
    answers, so each such pair is reported rather than resolved.
    """
    seen: dict[tuple[str, str], int] = {}
    for module in surface.get("modules", ()):
        for endpoint in module.get("endpoints", ()):
            for method in endpoint.get("methods") or [WEBSOCKET]:
                key = (method, endpoint["path"])
                seen[key] = seen.get(key, 0) + 1
    return [
        f"{method} {path}: served by {count} routes; the first one registered answers, "
        "and this check cannot say which that is"
        for (method, path), count in sorted(seen.items())
        if count > 1
    ]


def read_baseline(root: pathlib.Path) -> Any:
    """The committed baseline, or ``None`` when the project has not adopted the check."""
    path = root / SURFACE_ARTIFACT
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def served_routes(app: FastAPI) -> dict[str, frozenset[str]]:
    """Every path the composed app serves -> its HTTP methods, from the route table itself.

    The table the router answers from, walked through every included router at the path
    each route is really served under (``iter_route_contexts``, which FastAPI's own schema
    generation walks). It used to be ``app.openapi()``, and a route declared with
    ``include_in_schema=False`` is not in that document: one on a router included inside
    a module's router was served, was in no module's endpoints, and was reconciled
    against a document that did not list it, so nothing reported it. A WebSocket route,
    which the document never lists, is in the table too, under :data:`WEBSOCKET`.

    Outside ``/api/v1`` only an ``APIRoute`` is listed here: the plain routes and the
    mounts there are kernel routes, which the access graph reports with their own note.
    """
    served: dict[str, set[str]] = {}
    for context in iter_route_contexts(app.routes):
        route = context.original_route
        path = context.path or ""
        if isinstance(route, APIRoute):
            methods = set(context.methods or ())
        elif not path.startswith(API_PREFIX):
            continue
        elif isinstance(route, APIWebSocketRoute | WebSocketRoute):
            methods = {WEBSOCKET}
        elif isinstance(route, Mount):
            path, methods = f"{path}/*", {"*"}
        else:
            # A plain route, or a kind this walk does not know: served under the API
            # prefix, so listed, with every method when it names none.
            methods = set(getattr(route, "methods", None) or {"*"})
        served.setdefault(path, set()).update(method.upper() for method in methods)
    return {path: frozenset(methods) for path, methods in served.items()}


def unplaced_routes(
    served: Mapping[str, frozenset[str]], modules: Sequence[Mapping[str, Any]]
) -> list[dict[str, object]]:
    """Every served ``/api/v1`` method that no module's endpoint covers.

    A router included inside a module's router is served under a path the access model
    cannot recover, so its route is in the table and in no module's endpoints. Listed,
    never dropped: a route that is served and in no record is the one a comparison with
    the record cannot see.
    """
    covered: dict[str, set[str]] = {}
    for module in modules:
        for endpoint in module["endpoints"]:
            # A WebSocket endpoint carries no methods; it covers the served WebSocket.
            covered.setdefault(endpoint["path"], set()).update(endpoint["methods"] or [WEBSOCKET])
    unplaced: list[dict[str, object]] = []
    for path, methods in sorted(served.items()):
        if not path.startswith(API_PREFIX):
            continue
        missing = methods - covered.get(path, set())
        if missing - {WEBSOCKET}:
            unplaced.append({"path": path, "methods": sorted(missing - {WEBSOCKET})})
        if WEBSOCKET in missing:
            # No methods, as a module's own WebSocket endpoint has none.
            unplaced.append({"path": path, "methods": []})
    return unplaced


def unseen_routes(
    unplaced: Sequence[Mapping[str, Any]], surface: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """What a comparison with the record cannot see, each with the sentence that says so.

    A route the model could not place, and a method and path two routes serve. Either one
    makes "no difference" an answer about a surface that is not the one being served, so
    both halves refuse it before they compare anything.
    """
    return [
        {
            "kind": "unplaced",
            "methods": list(route.get("methods") or [WEBSOCKET]),
            "path": route["path"],
            "detail": (
                f"{','.join(route.get('methods') or [WEBSOCKET])} {route['path']}: served, but "
                "the access graph cannot place it (a router included inside a module's "
                "router); declare it on the module's own router"
            ),
        }
        for route in unplaced
    ] + [{"kind": "served_twice", "detail": line} for line in served_twice(surface)]


def _unreadable(reason: str) -> str:
    # An unreadable record is not an absent one: writing a fresh file over it would accept
    # whatever the app serves now, unseen. It is restored, not replaced.
    return (
        f"{SURFACE_ARTIFACT} cannot be read ({reason}), so the routes this app serves cannot "
        "be compared with it. Restore the committed file from version control: writing it "
        "again would accept whatever the app serves now."
    )


def _listed(lines: Sequence[str]) -> str:
    named = "\n".join(f"  - {line}" for line in lines[:_NAMED])
    if len(lines) > _NAMED:
        named += (
            f"\n  ... and {len(lines) - _NAMED} more "
            "(`terp verify --only authz-surface` lists every one)"
        )
    return named


def _problem(
    app: FastAPI, plane: ControlPlane, specs: Sequence[ModuleSpec], path: pathlib.Path
) -> str | None:
    """What stands between the composed app and its record, or ``None`` when they agree."""
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return _unreadable(str(exc))
    if not isinstance(record, dict):
        return _unreadable("it is not a JSON object")
    model = build_access_model(plane, specs)
    current = authz_surface(model)
    modules: Any = model["modules"]
    unseen = unseen_routes(unplaced_routes(served_routes(app), modules), current)
    if unseen:
        return (
            f"the routes this app serves cannot be compared with {SURFACE_ARTIFACT}: "
            f"{len(unseen)} route(s) are served in a way the record cannot hold:\n"
            + _listed([item["detail"] for item in unseen])
        )
    try:
        changes = authority_changes(record, current, model)
    except (AttributeError, KeyError, TypeError) as exc:
        return _unreadable(
            f"it is not a surface this version of the framework reads: {type(exc).__name__}: {exc}"
        )
    if not changes:
        return None
    ordered = [entry for entry in changes if entry["widens"]] + [
        entry for entry in changes if not entry["widens"]
    ]
    return (
        f"this app does not serve what {SURFACE_ARTIFACT} records: {len(changes)} "
        "difference(s):\n"
        + _listed(
            [f"{'widens' if entry['widens'] else 'narrows'}: {entry['change']}" for entry in ordered]
        )
        + "\nThe record is what the check before release compared this app with, so an app "
        "that composes differently here is not the app that was checked. If the code is "
        "right, write the record again in a change a reviewer sees, and release that:\n"
        f"  {ADOPT_HINT}\n"
        "If the record is right, find what composes the app differently here: a route or a "
        "module added under a condition."
    )


def startup_refusal(
    app: FastAPI, plane: ControlPlane, specs: Sequence[ModuleSpec], *, local: bool
) -> str | None:
    """Why this app may not start, or ``None``: it serves what its record says (ADR 0212).

    The runtime half of the ``authz-surface`` check, run by ``create_app`` over the app it
    just composed and froze (ADR 0208), so what is compared here is what will be served.

    The record is ``authz-surface.json`` in the working directory: the project root where an
    app is developed, and ``/srv`` in the image the deployment generator writes, whose
    ``Dockerfile.prod`` copies the record there. An app with no record there is not compared,
    as the check before release skips an app that never adopted it; outside local that is
    said in the log, so a process that was not checked does not read as one that was.

    *local* (``ENVIRONMENT=local``) turns the refusal into a warning: a developer who adds a
    route serves it at once and writes the record in the same change. An empty record is
    then passed over in silence, because the command that writes the record redirects into
    it, and the shell empties the file before that command composes the app. Everywhere
    else an empty record is an unreadable one, and refused.
    """
    path = pathlib.Path.cwd() / SURFACE_ARTIFACT
    if not path.is_file():
        if not local:
            _logger.info(
                "no %s in the working directory, so the routes this app serves were not "
                "compared with a record (ADR 0212). Adopt the check with: %s",
                SURFACE_ARTIFACT,
                ADOPT_HINT,
            )
        return None
    if local and path.stat().st_size == 0:
        return None
    problem = _problem(app, plane, specs, path)
    if problem is None:
        if not local:
            _logger.info("%s matches the routes this app serves", SURFACE_ARTIFACT)
        return None
    if local:
        _logger.warning(
            "%s\nOutside ENVIRONMENT=local this app refuses to start on this (ADR 0212).", problem
        )
        return None
    return problem


__all__ = [
    "ADOPT_HINT",
    "API_PREFIX",
    "SURFACE_ARTIFACT",
    "WEBSOCKET",
    "authz_surface",
    "read_baseline",
    "render_authz_surface",
    "served_routes",
    "served_twice",
    "startup_refusal",
    "unplaced_routes",
    "unseen_routes",
]
