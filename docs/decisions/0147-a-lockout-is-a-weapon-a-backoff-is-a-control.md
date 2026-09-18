# 0147 — A lockout is a weapon; a backoff is a control

- **Status:** Accepted and implemented. `LoginThrottle` applies exponential backoff keyed
  by `(identifier, caller address)` with a high identifier-wide backstop; nothing is ever
  disabled. `/login` and `/token` both use it. Held by
  `tests/architecture/test_session_revocation.py`,
  `tests/architecture/test_service_principals.py` and
  `apps/example/tests/test_session_revocation_api.py`.
- **Date:** 2026-09-18
- **Relates:** [ADR 0031](0031-session-management-token-revocation-and-login-lockout.md) (the lockout this
  replaces), [ADR 0036](0036-distributed-throttle-store.md) (the store both counters ride),
  [ADR 0088](0088-service-principal-credentials.md) (the grant that
  had no throttle at all), [ADR 0138](0138-a-mount-that-verifies-credentials-declares-its-own-rate-limit.md)
  and [ADR 0140](0140-a-mount-is-not-a-cost-class.md) (the rate-limit half of this
  finding, already shipped)

---

## Context

The login throttle counted failures per account and, at five within fifteen minutes,
**locked the account for fifteen minutes**. While locked, a correct password was refused
too — that was stated in its docstring as a feature, and a test asserted it by name.

That property is what makes a lockout attackable rather than defensive. Anyone who knows
an email address could take its owner offline on demand and keep them there, by failing
five logins every quarter of an hour, forever. The control was aimed at an attacker, but
the attacker could reach it and point it at the user. One piece of state, shared between
the two parties, spendable by either.

The client-credentials grant went the other way and shipped **no** throttle at all, on
reasoning recorded in the route: a lockout keyed on a client id would let anyone who
learns one take an integration offline. That reasoning is correct about lockouts. It was
taken as a reason to have nothing, and what it left behind is worse than the brute-force
question it declined to answer: every attempt runs a memory-hard KDF — the real
verification on a wrong secret, a dummy one on an unknown client id so that the miss path
costs the same and cannot be used as an oracle. An unauthenticated endpoint that hashes
before it throttles is a way to spend the server's CPU and memory that needs no valid
credential at all. The only thing standing in front of it was the global per-address rate
limit.

## Decision

**Exponential backoff on the attempt, never a state on the account.** A caller that keeps
failing waits longer and longer before another attempt is looked at. Nothing is marked
unusable, and the moment a wait elapses the next attempt is judged on its merits. The
cost lands very differently on the two parties, which is the whole design: someone who
mistypes twice notices nothing and on the third notices two seconds, while a guesser
doubles its wait every time and is soon spending minutes per try.

**The key is `(identifier, caller address)`, not the identifier.** This is the part that
disarms the weapon. An attacker hammering an address from their own network slows
*themselves*; the account's real owner, arriving from somewhere else, has a counter of
zero. Under the lockout there was one counter and either party could spend it on the
other.

**An identifier-wide backstop remains, tuned to be a poor lever.** A distributed guesser
spreading attempts across many sources would sail past a purely per-source control, so
the identifier keeps a counter — but it takes **fifty** failures to engage and then costs
**five minutes**, against the old five failures for fifteen. Ten times the work for a
third of the effect, self-healing, and still nothing disabled. The numbers are arguable
and both are constructor arguments; what is not arguable is the direction, because this
is the only state an attacker can still spend on somebody else and it should be expensive
to reach and cheap to recover from.

**`/token` is throttled by the same object.** The objection that killed it was about
lockouts and does not survive the change: keyed by `(client id, caller)`, a stranger
failing against an integration's client id slows only themselves, and the integration
authenticating from its own host is untouched. The check runs **before** verification, so
a refused attempt never reaches the KDF — which is what actually closes the CPU-exhaustion
half of the finding.

**The error is renamed.** `TooManyAttemptsError` (`too_many_attempts`) replaces
`AccountLockedError` (`account_locked`). The old name is kept as an alias so an existing
`except` clause still compiles, but the wire `code` changes, and that is deliberate rather
than incidental: a client that says *your account is locked, contact support* when the
user needs to wait four seconds is showing them a different product than the one running.
The remaining wait goes to `log_context` and not to the client — telling a caller exactly
how slowed they are is telling a guesser, who is the only audience that can act on it.

## Consequences

**Breaking, on the wire and in the constructor.** `code` moves from `account_locked` to
`too_many_attempts`; `max_attempts` / `lockout` give way to `free_attempts` /
`base_delay` / `max_delay` / `identifier_attempts`. `check`, `record_failure` and
`record_success` take an optional keyword `source`. Passing none collapses to
identifier-only backoff, which is right for a caller whose identifier already carries the
address — the OIDC callback key does, and needed no change.

**Brute-force resistance is not uniformly stronger, and the trade is explicit.** Against a
single source it is far stronger: the old control allowed five guesses per fifteen minutes
in bursts, this allows two and then doubles. Against fifty sources it is weaker than a
five-attempt lockout, by construction — that is the price of making the account
undisableable, and the backstop is what bounds it.

**The disarming depends on `client_ip` being the real caller, which is not yet
guaranteed.** `SecurityConfig.trusted_proxy_hops` defaults to `0`, and at `0` the
middleware ignores `X-Forwarded-For` and resolves every caller to the proxy's address.
An application behind a reverse proxy that has not declared its hop count therefore hands
this throttle **one** source for everybody — the pair key collapses, and the backoff is
per-identifier again. It is still strictly better than what it replaced (a bounded,
self-healing delay rather than a fifteen-minute disable), but the property this ADR is
named for is gone until the hop count is right. That is a separate open finding about the
deployment default, and this change makes it matter more than it did: a misconfiguration
that used to cost a shared rate-limit bucket now also costs the per-caller keying.

**A supplied store brings its own clock.** `LoginThrottle`'s injectable clock only reaches
the store it builds itself, so an app handing `create_app` one shared `InMemoryThrottleStore`
(ADR 0036) is clocked by that store. It is a testing sharp edge rather than a runtime one,
and the example app's end-to-end test now says so where somebody will hit it.

**One test changed sides.** `test_throttle_locks_at_the_threshold_and_refuses_even_a_valid_credential`
asserted the defect as intended behaviour — faithfully, which is why nothing caught it.
Its replacement asserts the inverse by name, and the example app's end-to-end test now
carries the second half too: a lockout and a backoff answer identically up to the first
429, and only what happens *after* tells them apart.
