# 0140 — A mount is not a cost class

- **Status:** Accepted and implemented. `ModuleSpec.rate_limit` is keyed by route
  (mount-relative path prefix, `"/"` for the mount itself) rather than being a single
  per-mount cap; the auth module declares `RateLimit.credentials()` on `/login` and
  `/token` only, and the OIDC module declares it at `"/"`. Held by
  `tests/architecture/test_security_middleware.py` and
  `apps/example/tests/test_login_wiring.py`.
- **Date:** 2026-09-16
- **Relates:** [ADR 0138](0138-a-mount-that-verifies-credentials-declares-its-own-rate-limit.md)
  (the declaration this re-keys), [ADR 0115](0115-a-path-family-gets-its-own-rate-limit-bucket.md)
  (the per-prefix buckets both fill), [ADR 0067](0067-a-mount-declares-its-own-request-body-allowance.md)
  (the per-mount declaration 0138 copied)

## Context

ADR 0138 gave a module the ability to declare its own rate limit, and keyed that
declaration to the module's mount — `/api/v1/<name>` — because that is how
`max_request_bytes` had already scoped a per-module allowance and a second scoping rule
would have been a second thing to learn.

The auth mount is where that copy stops holding, and it is not an edge case: it is the
mount the rule was written for. `RateLimit.credentials()` is thirty requests a minute,
and its justification is entirely about cost — every attempt runs a memory-hard hash,
including on the miss paths, so the endpoint is the cheapest place on the whole surface
to spend the server's CPU. That is true of `/login`. It is true of `/token`. It is not
true of the other two routes on the same mount.

`/refresh` reads a high-entropy cookie, looks it up, and rotates it. It costs a query.
It also happens to be the busiest authenticated route the platform has, because
`TerpProvider` posts to it on **every** mount to restore a session — so its volume
tracks page loads, not login attempts. `/logout` is the same shape.

The effect of capping all four together was that ordinary navigation was rationed at the
rate chosen to make password guessing expensive. The end-to-end suite is what surfaced
it — a suite whose requests all come from one runner address exhausted thirty in a
window and then failed with missing elements on pages that had simply been refused. That
is the mild version. The serious version is a shared egress address, where an office, a
school or a VPN exit is one caller: those users would have found the application
unusable after thirty page loads between them. `RateLimit.credentials()` names that exact
outcome as the reason a per-address *lockout* cannot exist — "it would let anyone take an
office offline" — and then the mount-wide cap reintroduced it on the busiest route.

## Decision

`ModuleSpec.rate_limit` is keyed by route. Keys are path prefixes relative to the mount,
so a module never spells its own `/api/v1/<name>`; `"/"` denotes the mount itself, which
is what a module declares when it really is one cost class. Longest prefix wins, which is
the resolution `_RateLimits` already performed — the change contributes finer prefixes to
a mechanism that was already prefix-based, rather than adding a second mechanism.

The auth module declares `{"/login": credentials(), "/token": credentials()}`. `/refresh`
and `/logout` fall through to the application's general limit, which is still a cap. The
OIDC module declares `{"/": credentials()}`: both of its routes are steps of the same
interactive sign-in, neither is reached on an ordinary page load, and it is genuinely one
cost class.

There is no scalar spelling retained alongside the mapping. A `RateLimit` and a
`{"/": RateLimit}` would be two ways to say one thing, and the mapping is the general
form.

## Consequences

The declaration now says something a mount cannot: *which* routes are expensive. That is
the fact the module owns and the composition root does not, which was ADR 0138's whole
argument — it was simply expressed at a granularity that could not carry it.

A key that is not a path prefix is refused at construction. `"login"` would compose to
`/api/v1/authlogin`, a prefix no request can ever have, so the cap would read as declared
in review and protect nothing; it fails where it is written instead.

The risk this accepts is that a route added to a capped mount is uncapped by default —
under ADR 0138 it would have inherited the mount's cap. That is the right default in both
directions here: inheriting a credential cap is what broke `/refresh`, and a new
credential-verifying route is being written by whoever also writes the declaration one
screen away. What makes it safe rather than merely chosen is that no route is ever
*unlimited* — the application's general limit is the floor everything falls back to, and
production already refuses a configuration that disables it.

`ModuleSpec.rate_limit` is normalised from a mapping to a tuple of pairs, as
`SecurityConfig.rate_limit_overrides` already is, because every other field on the frozen
dataclass is hashable and a dict field would quietly take that away.
