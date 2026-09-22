# 0138 — A mount that verifies credentials declares its own rate limit

- **Status:** Accepted and implemented. `ModuleSpec.rate_limit` declares a per-mount cap,
  `create_app` merges those declarations under `SecurityConfig.rate_limit_overrides`, and
  the auth and OIDC modules declare `RateLimit.credentials()`. Held by
  `tests/architecture/test_security_middleware.py`.
- **Date:** 2026-09-15
- **Relates:** [ADR 0067](0067-a-mount-declares-its-own-request-body-allowance.md) (the
  per-mount declaration this copies), [ADR 0115](0115-a-path-family-gets-its-own-rate-limit-bucket.md)
  (the per-prefix buckets it fills), [ADR 0031](0031-session-management-token-revocation-and-login-lockout.md)
  (the per-account lockout it sits beside)

## Context

ADR 0115 gave the rate limiter per-prefix buckets so that exhausting one path family
could not 429 another — "a credential endpoint and an asset read share a process, not a
counter", in its own words. The mechanism shipped. Nothing used it.

So every route ran under the general limit, whose default is 240 requests a minute. That
number is a reasonable posture for an application's ordinary traffic, where a request
costs a query. It was never chosen against what a credential endpoint costs, and a
credential endpoint costs something very unusual: an Argon2 verification, which is
memory-hard **on purpose**.

The part that makes this sharper than it first looks is that the expense is deliberate
on the miss paths too. `authenticate_client` burns `verify_password_dummy()` for an
unknown client id, and the password path does the same for an unknown email, because
otherwise the timing difference enumerates accounts. The property that makes the
credential check safe against a guesser is therefore the same property that makes the
endpoint the cheapest place on the whole surface to spend the server's CPU — and it is
reachable without a token, by anyone.

The client-credentials grant (`POST /token`) has no account lockout either, and
deliberately: a lockout keyed on a client id would let anyone who learns one take an
integration offline. That reasoning is right, but nothing replaced the control it
declined, so the mount was left with the general limit and nothing else.

The obvious fix — tell every application to add a `rate_limit_overrides` entry for
`/api/v1/auth` — is the wrong shape for the same reason ADR 0067 rejected it for request
bodies. The module that owns a surface is the only thing that knows what that surface
costs, and a control that depends on every consumer remembering a composition-root line
is a control most consumers will not have.

## Decision

**`ModuleSpec` declares its own rate limit**, exactly as it already declares
`max_request_bytes`. `create_app` derives the prefix→limit map from every *mounted*
spec (an unrouted spec is skipped — a prefix nothing serves has nothing to limit) and
lays `SecurityConfig.rate_limit_overrides` on top, so root overrides package as at every
other composition seam. That precedence matters more here than elsewhere: a deployment
that has measured its own login traffic must be able to say so, and a capability's
default is a floor it may move rather than a decision taken away from it.

**`RateLimit.credentials()` names the tier**: thirty per minute per caller. One attempt
every two seconds sustained, which no person reaches and no honest client needs, against
an eighth of the CPU the general limit would let one address spend. The auth and SSO
modules declare it, so installing the capability is the whole wiring.

**It is a ceiling on one address, not a defence against many**, and that is why it does
not replace anything. A distributed guesser is what the per-account lockout is for. The
two controls are deliberately different: a per-address lockout cannot exist (it would
let anyone take an office offline), and a per-account one cannot bound CPU, because the
attempt is paid for before the account is known. Each covers what the other cannot.

**A module may tighten its mount and never exempt it.** `ModuleSpec(rate_limit=...)`
refuses a disabled limit at construction, for the reason `production_problems()` already
refuses one in `rate_limit_overrides`: an unlimited declaration is a hole one prefix
wide, and a quieter one than a disabled global limit, because the global limit still
reads as enabled.

## Consequences

Applications inherit a tighter cap on their auth mount on upgrade, with no change of
their own. Thirty a minute per address is generous for human logins — a shared office
address reaching it would need one login every two seconds, sustained — but a deployment
whose clients poll `/refresh` aggressively, or that fronts many users behind one
egress IP with `trusted_proxy_hops` left undeclared, may need to raise it. That second
case is worth naming, because the two settings interact: with the proxy undeclared every
caller is keyed on the proxy's address, so the credential bucket is shared by everyone,
and the tighter cap will surface that misconfiguration much sooner than the general one
did. Surfacing it is the better outcome; the remedy is to declare the hops, not to raise
the limit.

The rate limit does not solve the distributed case, and no rate limit can. What it
removes is the single-address version, where one caller could spend four minutes of
server CPU every minute from a laptop.
