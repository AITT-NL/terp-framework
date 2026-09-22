# 0148 — A route declares its own posture, not its neighbours'

- **Status:** Accepted and implemented. `route_policy(Policy)` declares one route's
  posture; the guard and the access projection both resolve it through
  `terp.core.routing.effective_policy`, and boot refuses an undeclared route in a public
  module. Held by `tests/architecture/test_route_policy.py`.
- **Date:** 2026-09-18
- **Relates:** [ADR 0016](0016-permission-in-policy-enforced-as-grant.md) (the module `Policy` this refines),
  [ADR 0102](0102-route-operations-are-declared.md) (the declaration this sits beside),
  [ADR 0121](0121-a-module-role-is-an-assignment-not-a-policy.md) (the one-decision rule the resolver preserves),
  [ADR 0139](0139-who-can-reach-what-is-pinned-not-merely-reportable.md) (the baseline
  that recorded the narrowing this produced)

---

## Context

`create_app` mounts exactly one `build_guard(spec.policy)` per module, as a router-level
dependency. A `Policy` is therefore a property of a whole router: one read requirement
and one write requirement for every route under it.

That is fine until a module needs two answers, and the mechanism gives it no way to say
so. `Policy.public_write` made **every** route in its module unauthenticated — the ones
that genuinely must be, and any route an author added beside them afterwards. Nothing
announced the second case. The only way to tighten one route inside a public module was
to hang `require_permission` on it, which works by a side effect explained in a comment
rather than by anything in the policy API.

**The cost was not hypothetical, and the platform was already paying it.** The realtime
capability is `Policy.public_write`, because an `EventSource` or `WebSocket` constructor
cannot attach a bearer header and the handshake redeems a one-use ticket instead. Under
that module policy sat `POST /tickets` — the endpoint that *mints* those tickets, which
is the authenticated step. It carried this:

```python
if principal is None:
    # Defensive: the module guard already rejects this endpoint, but the
    # handler remains fail-closed when called directly in tests.
```

The comment was false. The module guard admitted everyone, and that hand-rolled check
was the only thing in front of the mint endpoint. Anyone who deleted it on the strength
of the comment would have published ticket minting to the internet. This is exactly the
shape the model produces: authority that lives in a handler and a stale sentence, because
the policy API had nowhere to put it.

## Decision

**`route_policy(policy)` declares one route's posture**, applied below the route
decorator beside `@operation`. The declared policy *replaces* the module's for that
route — it does not merge, and it is not restricted to narrowing. A public module can
carry a protected route and a protected module a public one, and in both directions the
answer is written on the route rather than inferred from its neighbours.

**One resolver, read by both the gate and the pane.** `effective_policy(module, endpoint)`
is called by the guard and by `authz.endpoint_json`. This is the part that is not
negotiable: a projection that kept describing the module while the gate enforced the
route would show an administrator a matrix the system disagrees with, and two copies of
one authorization decision is a defect this repository has already had to repair once
(ADR 0121 §4). The guard reads the matched route out of the ASGI scope, which Starlette
populates before any dependency runs.

**Boot refuses an undeclared route in a public module.** Every route under a
`Policy.public*` module must say what it is. In practice they all end up marked public,
which looks like ceremony until the next route arrives: that one fails at boot instead of
being quietly published. The check asks only of *public* modules — a protected module's
routes inherit a safe default and need no ritual — and it walks WebSocket routes too,
since a socket has no method after the upgrade and is treated as a write.

**The existing public-write refusal moved to the route.** It now measures each mutating
route against its *effective* policy, so a route that declared itself protected inside a
public module is no longer asked to justify an unauthenticated write it does not perform.

## Consequences

**`POST /api/v1/realtime/tickets` is no longer public.** The committed authorization
baseline records the narrowing in one line — `public` → `role:viewer` for all three
rungs — which is ADR 0139 doing precisely what it was built for. It is gated at VIEWER
rather than the EDITOR a bare `Policy.default()` would impose: minting a ticket is a POST
that subscribes, not one that changes anything, and the authority that actually decides
is the channel's own check. Defaulting would have refused every VIEWER a realtime
channel, which is most of the people a realtime channel exists for.

**A factory-built route has no decorator, and does not need one.** `route_policy` is an
ordinary function; the decorator form is sugar. A router built by `build_crud_router` (or
any `add_api_route` call) is marked by applying it to the endpoint, which is what the
fixtures for those shapes now do.

**Thirty-three fixture routes gained a declaration.** That is the one-time cost of the
boot refusal, and it is concentrated in tests because tests are where throwaway public
modules live. Each was marked from the AST — by finding the `ModuleSpec` whose `policy=`
is public and the *name* it passes as `router=` — rather than by matching route
decorators with a regex, because getting that wrong marks a route public that should not
be, which is the exact harm the check exists to prevent.

**Nothing changes for a module that was already correct.** A route that declares nothing
resolves to its module's policy, so every existing protected module behaves as before.
