# 0161 — A module that only reads says so

- **Status:** Accepted and implemented. `ModuleSpec(read_only=True)` is refused at boot by
  `create_app` when any route of the module could write. Held by
  `tests/architecture/test_read_only_modules.py`.
- **Date:** 2026-09-28
- **Relates:** [ADR 0102](0102-route-operations-are-declared.md) (where `@read_only`, the
  per-route declaration this builds on, is recorded beside the other route markers),
  [ADR 0148](0148-a-route-declares-its-own-posture-not-its-neighbours.md) (the per-route
  policy this must not be undone by), [ADR 0040](0040-adversarial-review-fourth-batch.md)
  (the public-module refusal this is the authenticated counterpart of),
  [ADR 0103](0103-the-ideology-one-pattern-enforced-escapable-by-proof.md) (a guarantee the
  platform can hold is held by the platform)

---

## Context

A module is often written to read and never to write: a view over records another process
produces, a search over a table a worker fills, a report. Terp could already say that about
one route — `@read_only` declares a handler pure, and the runtime binder marks a `GET` or a
declared route read-only so a write through the chokepoint fails closed. It could not say it
about a module. `Policy.public` is read-only by construction, and boot refuses a write route
in a public module unless it takes the stronger `Policy.public_write`. An authenticated module
had no equivalent, so its read-only-ness was a guarantee made of missing code: it held until
someone added a `POST`, and nothing would notice.

The friction was reported from an app whose module serves records that only a separate worker
may write. Its author held the line with a hand-written test: walk `router.routes`, fail on any
method but `GET` or `HEAD`. Measured on FastAPI 0.139, that test has a hole. `include_router`
keeps a sub-router as a nested `_IncludedRouter` instead of flattening its routes, so a `POST`
added one router down is invisible to the scan and the test stays green. The framework can
walk the composed router properly — into included routers, and over WebSocket routes, plain
Starlette routes and mounts as well as FastAPI's — which is the argument for it owning the check
rather than every app writing its own.

## Decision

**`ModuleSpec` gains `read_only: bool = False`.** Declared, every route of the module must be
one the runtime binder already marks read-only, and `create_app` refuses the boot otherwise:

- an HTTP route with no method in `MUTATING_METHODS` boots;
- any route declared `@read_only` boots, HTTP or WebSocket, because that is the binder's own
  test and the route then computes rather than persists;
- anything else is refused — a route answering `POST` / `PUT` / `PATCH` / `DELETE`, one
  registered with several methods of which one is mutating, and a WebSocket, which has no
  method after the upgrade and which the guard already treats as a write;
- a plain Starlette route (`add_route`) or a `Mount` never reaches this check. FastAPI serves
  it without the router's dependencies, so neither the binder nor the policy guard runs for it
  — measured while this was reviewed: an unauthenticated `POST` to either answered 200 in a
  module behind `Policy.default()`. It is refused in every module, declared or not
  ([ADR 0166](0166-a-module-router-carries-only-routes-the-guard-can-see.md)).

The refusal names the module, the route's path and its handler, and the way out: move the
route to a module that writes, or declare it `@read_only` if it persists nothing. The handler is
named because a route on an included sub-router reports its path relative to that router, and
the path alone can be ambiguous. Measured before relying on it: the binder does run for a
WebSocket route, and a `@read_only` one executes with the read-only flag set.

The runtime half needs nothing new. Every route that boots is one the binder marks read-only,
so a write that reaches the chokepoint anyway — through a helper, a subscriber, a capability —
fails closed exactly as it does in a `GET` today.

**It is a property of the module, not of `Policy`.** A `Policy` answers who may call, and ADR
0148 lets a route replace its module's policy outright. Were read-only a kind of policy, a
route could reopen writes by declaring `route_policy(Policy.default())`, and the declaration
would be one line away from meaning nothing. Read-only answers what the routes do, which is the
axis `@read_only` and `BaseService.append_only` already sit on, so it sits there too, and a
per-route policy cannot touch it. Authorization is unchanged: a declared `@read_only` `POST` in
such a module is still authorized at the write tier, for the reason `terp.core.routing` gives.

**No build-time rule.** The boot check reads the composed router — nested routers,
`add_api_route`, WebSockets, plain routes and mounts — where a source scan would approximate it, and it cannot be
silenced by a marker. Every test that composes the app reaches it, so an app's own suite fails
on the change that breaks the promise. A catalog rule would duplicate it less precisely.

## Consequences

- An app gains nothing and loses nothing on upgrade; the field defaults to `False`, and a
  module that does not declare it behaves exactly as before.
- The hand-written "no write route" test an app keeps for such a module can be replaced by the
  declaration, which also covers what that test missed.
- The declaration is about the module's HTTP surface. Its jobs and subscribers are not requests
  and are not covered; a module whose background work must not write either needs that said
  where the work runs.
- A module declared `read_only` with no router is vacuously true and is not refused.
- A plain Starlette route or a mount in a module that does *not* declare `read_only` was
  served outside the guard as well. This record first left that open as a decision of its own;
  [ADR 0166](0166-a-module-router-carries-only-routes-the-guard-can-see.md) takes it and
  refuses one in every module.
