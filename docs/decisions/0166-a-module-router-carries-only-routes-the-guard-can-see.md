# 0166 — A module router carries only routes the guard can see

- **Status:** Accepted and implemented. `create_app` refuses a plain Starlette route, a
  Starlette WebSocket route or a mount on any module router. Held by
  `tests/architecture/test_module_routes_are_guarded.py`.
- **Date:** 2026-09-28
- **Relates:** [ADR 0161](0161-a-module-that-only-reads-says-so.md) (where the gap was found,
  and first closed for `read_only` modules only), [ADR 0148](0148-a-route-declares-its-own-posture-not-its-neighbours.md)
  (the per-route policy a route anyone may call declares instead),
  [ADR 0103](0103-the-ideology-one-pattern-enforced-escapable-by-proof.md) (the default is the most
  enforced standard, and a second way to do a supported thing is refused)

---

## Context

`create_app` guards a module by mounting its router with dependencies: the deny-by-default
policy guard, the audit-actor binder and the read-only binder. FastAPI attaches router
dependencies to its own routes only. A plain Starlette `Route` registered with `add_route`, a
Starlette `WebSocketRoute` and a `Mount` are served without them, so none of the three runs.

Measured while ADR 0161 was reviewed: in a module behind `Policy.default()`, an unauthenticated
`POST` to a route from `add_route`, and to a sub-application mounted on the module's router,
both answered 200. The build-time rule `no_raw_app_routes` refuses `add_route`, `mount` and
`add_websocket_route` in app code, with a budgeted escape marker. It does not see
`router.routes.append(...)`, and the marker, where one is spent, reaches nothing at runtime:
the route boots unguarded. That is a control on one layer only, which AGENTS.md convention 4
says a runtime-observable invariant must not be.

ADR 0161 closed it for a module declared `read_only` and recorded the general case as a
decision still to take, because refusing a mount in every module also takes away the one
thing the marker bought.

## Decision

**`create_app` refuses any route on a module router that is not a FastAPI route.** The walk
covers every included router. The refusal names the module, the kind of route and its path,
and the two ways out: register it with a route decorator or `add_api_route`, and declare
`route_policy(Policy.public(reason=...))` if anyone may call it.

**There is no runtime escape.** What a mounted application or a raw route achieves can be had
through a FastAPI route — a public one where the surface is meant to be open — so refusing the
other spelling removes a second way of doing a supported thing, not a capability. A consumer
that shows otherwise gets a declared, reasoned escape then, not a quiet one now.

The `read_only` check keeps its own concern — what a FastAPI route may do — and no longer
repeats this one.

## Consequences

- An app that mounts a raw route or a sub-application on a module router is refused at boot,
  with the fix in the message. None of the framework's capabilities, its example app or its
  template does; the composed example app was walked to confirm it.
- `no_raw_app_routes` stays as the early, build-time half. Its marker still governs surface
  registered on the composed app itself, which this check does not read.
- One walker yields every route and one yields the FastAPI routes a declaration can sit on;
  both live in `terp.core.routing`, and the composition root's HTTP-only walk is the second
  narrowed to HTTP rather than a third copy.
