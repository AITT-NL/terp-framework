# 0115 — A rate limit is scoped the way a body cap already is

- **Status:** Accepted
- **Date:** 2026-09-05
- **Relates:** [ADR 0067](0067-per-module-request-size-allowances.md) (the per-mount body cap
  this borrows its shape from, down to the longest-prefix rule),
  [ADR 0036](0036-distributed-throttle-store.md) (the counter store a scoped limit writes
  into, and why a store error denies),
  [ADR 0006](0006-cross-cutting-controls-and-opinionation-policy.md) (a seam ships a safe default; this one
  changes nothing until an app declares an override)

---

## Context

`SecurityConfig.rate_limit` is one `RateLimit` for the whole application:
`RateLimit(requests=240, window_seconds=60)`, one fixed window, keyed on the client IP for
every request that reaches the app.

**One number cannot be right for two kinds of endpoint.** A credential endpoint wants a limit
low enough that guessing is impractical — single digits per minute per address. A page that
loads thirty assets wants a limit high enough that one screen does not exhaust it. A single
number is either too loose for the first or too tight for the second, and the value that
ships is necessarily the loose one, because the tight one would break ordinary browsing. So
the control exists, is enabled, is reported in headers, and is set to a number chosen by
whichever endpoint tolerates the least protection.

The framework already solved this exact problem for a different limit. A request body cap is
global *plus* a per-mount override map, resolved by longest matching path prefix (ADR 0067),
because a file upload and a JSON PATCH cannot share a byte ceiling either. `_RequestSizeCaps`
is that resolver, and the recent idempotency fix made both body-bounding middlewares hold the
same instance so the documented allowance means one thing.

There was no argument for the rate limit being different. There was only that nobody had
moved it.

## Decision

**`SecurityConfig` gains `rate_limit_overrides`: a path prefix to its own `RateLimit`,
longest prefix wins, everything unmatched keeps the global limit.**

The shape is deliberately identical to the body-cap map, and `_RateLimits` is deliberately a
near-copy of `_RequestSizeCaps`. Two controls that scope themselves to a path in two
different ways would be two things to learn and two places to be wrong; the duplication of a
twelve-line resolver is the cheaper of the two costs.

**A scoped limit gets its own counter, and that is the substance rather than a detail.** The
counter key carries the matched prefix, so `/api/v1/auth` is tallied separately from
everything else. A scoped limit that shared the global counter would be a second *ceiling*
on one tally rather than a separate *allowance*: a burst of asset reads would still consume
the budget that a login needs, which is the failure the whole change exists to prevent. The
test that would catch that regression asserts exactly it — exhaust the scoped bucket, then
show the global one is untouched.

**A prefix is a path prefix, not a string prefix.** `/api/v1/authorised` is not under
`/api/v1/auth`. This is inherited from the body-cap resolver, along with its test.

**The response headers report the limit that actually applied**, not the global one. A client
that reads `X-RateLimit-Limit` to pace itself has to be told which bucket it is in, or a
scoped limit is invisible until the moment it refuses. This mirrors the 413 that now names
the cap that applied rather than the one it was configured with.

### The production posture

An override may lower a limit or raise it. It may **not** remove one:
`production_problems()` refuses a disabled override and names the prefix. A global limit set
to zero was already refused; one path family exempted is the same hole and a quieter one,
because the global limit still reads as enabled and nothing else in the config says a family
of paths is uncounted.

A key that is not a path prefix is refused at construction. A malformed key would match
nothing and read, to anyone auditing the config, as a limit that had been applied — the worst
failure mode a security declaration has, because it is both silent and reassuring.

### What this does not do

**No per-route declaration on the route itself.** Prefixes, not decorators. A limit attached
to a handler is invisible from the security config, so the question "what does this app
actually enforce" stops having one answer; and the prefix map already covers the case that
motivated this, because the endpoints that need their own budget arrive in families
(`/api/v1/auth/...`) rather than one at a time. A decorator can be added later on top of this
without contradicting it; the reverse is not true.

**No change to the key.** A limit is still per client address per bucket. Keying on an
authenticated principal is a different decision with a different failure mode — it moves the
control after authentication, which is precisely where a credential endpoint cannot put it.

## Consequences

**Nothing changes for an app that declares no overrides.** The default is an empty map, the
global limit applies everywhere, and the resolver returns the global tuple for every path.
The one observable difference is internal: the counter key gained a bucket segment (`rl::<ip>`
where it was `rl:<ip>`). For the in-memory default that is invisible. A deployment on a shared
store sees each key start a fresh window once, on the deploy that ships this — one window, at
most one request's worth of extra allowance, and no way for it to lift a limit for longer than
that.

**An app can now write down what it actually wants**, and the declaration is in the same place
as every other security control rather than in a middleware argument or a decorator.

## Alternatives considered and not taken

**Leave it global and tell apps to add their own middleware.** This is what the absence
amounted to, and it is the pattern the platform refuses elsewhere: an app that adds its own
middleware is outside the composition root's control, invisible to the security config, and
outside `no_adhoc_middleware`. A control every serious app has to re-add by hand is a missing
control.

**Per-route declarations on the router.** Rejected above: a limit that lives on a handler
cannot be read off the security declaration, and the security declaration is the artifact
someone audits.

**One shared counter with a per-prefix ceiling.** Simpler — no bucket in the key, one tally,
several ceilings against it. It is also the version that does not work: a low ceiling on a
shared tally means any other traffic can exhaust the credential endpoint's budget, so the
tighter the limit you declare for logins, the easier it becomes to lock logins out. A limit
that is easier to weaponise the more carefully it is set is worse than none.
