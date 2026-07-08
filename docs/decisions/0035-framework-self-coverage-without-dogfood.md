# 0035 - Framework self-coverage: the bundled stack is exercised without the dogfood

- **Status:** Accepted
- **Date:** 2026-06-29
- **Context phase:** Phase 3 (enforcement harness) -- closes the STATUS self-coverage gap
- **Relates:** [ADR 0003](0003-conformance-and-coverage-gate.md) (the 100% line-coverage
  gate this preserves: `--cov=terp`, `fail_under=100`), [ADR 0021](0021-create-app-middleware-seam.md)
  (the `TenantMiddleware` composition seam reused here), [ADR 0031](0031-session-management-token-revocation-and-login-lockout.md)
  (the revocable provider + login lockout the stack wires), [ADR 0007](0007-audit-auto-emit-and-the-audit-seam.md)
  (durable audit sink). Source of truth: [AGENTIC_PLATFORM_DESIGN.md](../../AGENTIC_PLATFORM_DESIGN.md).

---

## Context

The `--cov=terp` gate held 100% only because `apps/example` exercised the bundled
capabilities end-to-end: the auth login/logout router, the users admin surface, the
access grants router, the audit-log router, and `TenantMiddleware` were covered by the
dogfood, not by framework-level tests. The STATUS tracker recorded this as the
**framework self-coverage gap** -- framework-only tests covered ~95.5% of `terp.*`; the
rest was reachable only through the example app. That couples a maintained-core invariant
to a client app: the dogfood was load-bearing, not additive, and a future dogfood
removal would silently drop the gate below 100%.

## Decision

Backfill **framework-owned** tests so `terp.*` reaches 100% from `tests/` alone -- the
example becomes purely additive. A single integration module assembles the *same* stack
the example wires, from framework packages only, over an in-memory database:

- `tests/architecture/test_framework_stack.py` builds `create_app([login, users, access,
  audit])` with the revocable `IdentityService` provider, the `persist_audit` durable
  sink, the `enforce_permission` seam, and `TenantMiddleware` through the sanctioned
  `create_app(middleware=...)` root; it drives login/logout (incl. epoch revocation),
  the users admin lifecycle + self/last-admin guards, grant create/list/delete, the
  audit log, and unit-covers the tenancy predicate/context, identity authenticate paths,
  the `BaseService` conflict mapping, and the `require_permission` dependency.

No production logic changed: this is tests only. The gate stays defined over the full
suite, `fail_under=100` is **unchanged**, and the example coverage is now redundant
rather than required.

## Consequences

- The dogfood can be refactored or removed without dropping the coverage gate; the
  maintained core no longer depends on a client app to prove it is fully exercised.
- The bundled stack has a framework-level smoke test that fails closed if a capability
  router/service path regresses, independent of any example.
