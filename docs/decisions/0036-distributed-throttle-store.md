# 0036 - Distributed throttle: a pluggable shared store for rate limiting + login lockout

- **Status:** Accepted
- **Date:** 2026-06-29
- **Context phase:** Phase 2 (base profile), distributed-correctness follow-up
- **Relates:** [ADR 0031](0031-session-management-token-revocation-and-login-lockout.md)
  (§5 shipped the per-instance `LoginThrottle` and explicitly **deferred the shared
  store** for "correct multi-instance behavior"), [ADR 0005](0005-security-middleware-and-structured-logging.md)
  (the per-instance `RateLimit` middleware this generalises), [ADR 0006](0006-cross-cutting-controls-and-opinionation-policy.md)
  (the Tier-A/B quadruple — registry + safe default · fail-closed runtime · build-time
  test · budgeted escape hatch), [ADR 0007](0007-audit-auto-emit-and-the-audit-seam.md)
  (the `…disabled(reason=…)` opt-out shape reused). Calibrates
  [IMPLEMENTATION_PLAN §10](../internal/IMPLEMENTATION_PLAN.md) ("distributed rate-limit
  (shared store)" backlog).

---

## Context

Two on-by-default DoS controls keep state in a per-process dict:

- the request **rate limiter** (`RateLimitMiddleware`, a fixed-window counter keyed by
  client host, ADR 0005), and
- the per-account **login lockout** (`LoginThrottle`, a failed-login counter + lockout
  keyed by email, ADR 0031 §5).

Both were documented as deliberately *per app instance / in process*: a single worker is
protected, but a horizontally-scaled deployment of N instances dilutes every limit by N
(≈ N× the configured rate, ≈ N× the failed-login budget before lockout) because each
worker counts only its own slice of traffic. ADR 0031 named the shared store a "later
enhancement"; this is it. The fix must keep the **default unchanged** (single-process
apps and the whole test suite must behave exactly as before), stay secure-by-default,
and ship as the ADR-0006 quadruple. Like ADRs 0031/0032 this is runtime + boot only —
there is no module-authored pattern to ban, so **no `terp.arch` AST rule applies**.

## Decision

Factor the shared state behind one small **`ThrottleStore` seam** in `terp.core`, used by
both controls; default to an in-memory implementation; let a multi-instance deployment
plug a shared backend (e.g. Redis); fail **closed** if the backend errors.

### 1. The seam (core, layer-0)

- `ThrottleStore` (ABC): `hit(key, window) -> (count, reset)` (fixed-window counter),
  `lock(key, seconds)`, `locked(key) -> int` (remaining lock seconds, 0 = unlocked),
  `clear(key)`. Times are integer seconds; one store serves several controls because
  callers namespace their keys (`rl:` rate limiter, `lt:` login throttle), so they never
  collide.
- `InMemoryThrottleStore` is the **safe default**: a dict under a lock, an injectable
  clock — byte-for-byte the historical per-instance behaviour. Exported from `terp.core`
  so the kernel middleware and the auth capability share one type.

### 2. Both controls consume it

- `RateLimitMiddleware(store=…)` (defaults to a fresh in-memory store); `create_app(…,
  throttle_store=None)` passes one store down. `LoginThrottle(store=…)` defaults to its
  own in-memory store. A deployment hands the **same** store to both seams for one
  correct global limit.
- **Fail-closed.** A store that raises makes the rate limiter return 429 and the throttle
  raise `AccountLockedError` — a backend outage tightens, never lifts, the limit.

### 3. Quadruple (ADR 0006) + default unchanged

- **Registry + safe default:** `throttle_store` defaults to `InMemoryThrottleStore`.
- **Fail-closed runtime:** store error → deny.
- **Build-time test:** the kernel suite (`test_throttle_store.py`) covers the seam, the
  shared-store path, fail-closed, and `create_app` wiring; no AST rule (no module pattern).
- **Budgeted escape hatch:** the existing reason-bearing `RateLimit.disabled()` /
  `LoginThrottle.disabled(reason=…)` stay the only way off.

## Consequences

- A multi-instance deployment gets one correct global rate limit and lockout by passing a
  shared store; single-process apps and tests are byte-for-byte unchanged.
- Auth still imports only the `terp.core` public surface; the store is a core type, not a
  new dependency. The example app dogfoods it (one `throttle_store` to both seams).
- No new table, no new boot flag: a shared backend is a drop-in store, not a config tier.

## Alternatives considered

- **A control-plane flag forcing a shared store in production.** Rejected: it would
  change the default and break minimal/single-process deploys; the store stays opt-in.
- **Two separate stores.** Rejected: the namespaced-key single store is simpler and lets
  one backend cover both controls.
- **A `terp.arch` rule.** Not applicable — the state is framework-internal; the second
  layer is the kernel test + fail-closed runtime, per ADR 0006 "where the shape allows".
