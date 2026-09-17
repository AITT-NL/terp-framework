# 0142 — An application's rate-limit override outranks a capability's, at any depth

- **Status:** Accepted and implemented. `_rate_limit_override_map` drops the
  capability-declared keys beneath an application override; production states once, in the
  log, which capability limit an application has raised. Held by
  `tests/architecture/test_security_middleware.py`.
- **Date:** 2026-09-17
- **Relates:** [ADR 0115](0115-a-rate-limit-is-scoped-the-way-a-body-cap-already-is.md) (the override
  seam whose documented precedence this restores), [ADR 0138](0138-a-mount-that-verifies-credentials-declares-its-own-rate-limit.md)
  (the capability declaration), [ADR 0140](0140-a-mount-is-not-a-cost-class.md) (the change
  that broke the precedence, correctly and invisibly), [ADR 0067](0067-per-module-request-size-allowances.md)
  (the sibling seam that did not break, and why)

## Context

`_rate_limit_override_map` has always carried this sentence:

> `SecurityConfig.rate_limit_overrides` still wins on a shared prefix. The precedence is
> the same one every other composition seam uses — the root overrides the package — and it
> matters more here than elsewhere: a deployment that has measured its own login traffic
> must be able to say so, and a capability's default is a floor it may move rather than a
> decision taken away from it.

It was true when written. The auth capability keyed its declaration on its **mount**, so an
application override on `/api/v1/auth` was the same dict key and replaced it. One line, one
key, root wins.

ADR 0140 re-keyed the capability by **route**: `/login` and `/token` capped,
`/refresh` deliberately not, because `/refresh` rotates a cookie for the price of a query
and the frontend posts to it on every mount, so its volume tracks page loads rather than
login attempts. That was the right fix for the problem it addressed.

It also ended the precedence, because the limiter resolves by **longest matching prefix**.
From that commit, `/api/v1/auth/login` (the capability's) outranked `/api/v1/auth` (the
application's). An application override on the mount stopped applying — and stopped in the
worst available way: declared in source, visible in review, counted by nobody. No warning,
no error, no failing test, and a docstring one screen above still promising the opposite.

It was caught within a release, and that is luck rather than process: 0.23.0 shipped the
re-keying and the very next consumer upgrade exercised it against a suite large enough to
notice. Had no application declared an override in that window, the promise could have
stayed false indefinitely — nothing was watching it.

**What it cost to find.** A consumer upgrading two releases hit 429s on `/auth/login` in a
conformance suite that signs in once per spec. The obvious reading — the limit is too low —
is wrong, and the fix that follows from it (raise the application's general limit) does
nothing, because an override-matched path is counted in its own bucket. The second obvious
reading — declare an override for the auth mount, which is what a security audit had
recommended in as many words — also does nothing, for the reason above. The diagnosis
needed someone to read `cap 30 requests/window` in a CI log and disbelieve a docstring.

**The sibling seam did not break, and the reason is the design.**
`_request_size_override_map` (ADR 0067) is keyed by **module name**, not by free-form path:
both the spec's contribution and the root's override compose to the identical
`/api/v1/<name>`, so overwrite is guaranteed, and an unknown name is a `BootError` rather
than a silent no-op. The rate-limit seam takes an arbitrary prefix string, which is more
expressive and has no such guarantee. Expressiveness bought the defect.

## Decision

**A root override covers a path family, and covering means covering.** Applying
`SecurityConfig.rate_limit_overrides` now removes every capability-declared key at or
beneath the override's prefix before inserting it. "The root overrides the package" has to
mean this once the package can key deeper than the root does; anything else makes the
precedence a function of who happened to write the longer string.

**The separator is part of the prefix.** `/api/v1/authority` is not beneath
`/api/v1/auth`. Coverage is `key == prefix or key.startswith(prefix + "/")`, and both the
map and the notice below are pinned against a sibling mount that shares a name stem —
without the separator an override silently uncaps an unrelated capability, which is the
same class of defect one level along.

**An application that wants the finer split keeps it by saying so.** Overriding the mount
collapses the capability's per-route distinction, including exemptions like `/refresh`.
That is a decision the application is now able to make rather than one made for it by a
sort order — and the project template, which ships a conformance suite that outgrows the
credential limit, declares its override **per route** for exactly this reason: a mount key
would drag `/refresh` into the credential bucket and undo ADR 0140 in the app that adopted
it.

**Production says which capability limit it is running above.** Restoring the precedence
turns a dead lever into a live one, and the lever points at the routes that run a
memory-hard hash on the miss path. `production_problems` already refuses the one move that
is never right — disabling a limit — so this is not a refusal: raising the number is
legitimate and sometimes necessary. It is one line at boot naming the prefix, the new
number and the capability routes it displaced, in the shape
`_warn_unshared_idempotency_in_production` established. An author who reads it before
shipping has the whole picture; one who reads it afterwards has the explanation.

## Consequences

**This changes production behaviour for any application that already declares an override
on a mount prefix.** Today that declaration is inert. After this release it takes effect.
An application that wrote a loose number for `/api/v1/auth` and has been unknowingly
protected by the bug loses that protection on upgrade — the boot notice is what makes the
change visible, and this is recorded in the changelog as a behavioural change rather than
as a pure fix, because for those deployments it is one.

**The real defect was the missing test, not the missing line of code.** ADR 0140's own
suite was thorough about what it changed and silent about what it displaced, because the
displaced property lived in a docstring. A guarantee stated in prose and held by nothing is
a guarantee with a half-life. The tests added here assert the promise directly — an
override covering a route wins, an override covering nothing takes nothing away, a sibling
stem is not covered — so the next re-keying fails instead of quietly repealing it.

**The expressiveness stays, with its cost named.** Keying overrides by module name, as ADR
0067 does, would make silent mismatch impossible and was considered. It was refused because
a path family is genuinely not always a module — an application may want to limit a subtree
of one — and because the fix above restores the property the name-keyed design was buying.
The residual is that a prefix matching nothing is still accepted silently; that is worth
revisiting if it bites, and is not this ADR.
