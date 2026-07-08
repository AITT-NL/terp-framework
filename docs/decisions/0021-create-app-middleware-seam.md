# 0021 - First-class middleware composition seam in `create_app`

- **Status:** Accepted
- **Date:** 2026-06-25
- **Context phase:** Phase 2 (base profile), adversarial-review follow-ups
- **Relates:** [ADR 0014](0014-adversarial-review-hardening.md) (the adversarial
  review — finding **H8**), [ADR 0005](0005-security-middleware-and-structured-logging.md)
  (the security middleware stack `create_app` installs and the `no_adhoc_middleware`
  rule), [ADR 0001](0001-terp-namespace-and-kernel-scope.md) (the composition root
  owns assembly; the kernel stays capability-agnostic). Finding **H8** in
  [docs/internal/reviews/2026-06-24-adversarial-design-review.md](../internal/reviews/2026-06-24-adversarial-design-review.md).

---

## Context

The `no_adhoc_middleware` rule (ADR 0005) forbids app / module code from calling
`add_middleware`, subclassing `BaseHTTPMiddleware`, or using `@app.middleware(...)`,
so the HTTP security posture is one central declaration. But the tenancy
capability's `TenantMiddleware` — a pure-ASGI middleware that binds
`tenant_context` per request from the verified token — **must** be installed via
`add_middleware`. The framework therefore forbade the exact operation its own
flagship multi-tenant feature requires: the only place tenancy was wired was
`apps/example/tests/test_tenant_middleware.py`, and `tests/` is arch-exempt. The
shipped `main.build()` never wired tenancy, so the multi-tenant guarantee existed
only in test scaffolding. (H8.)

## Decision

Give `create_app` a first-class `middleware=` seam:
`create_app(..., middleware: Sequence[Middleware] | None = None)` passes the
app-supplied Starlette `Middleware` list to the `FastAPI(...)` constructor.
Because the central security stack is attached afterwards with `add_middleware`
(which prepends), the app-supplied middleware lands **innermost** — just around
the routes, inside request-id / security-headers / CORS / rate-limit / body-size —
which is exactly where a per-request `tenant_context` binding belongs.

The kernel owns `add_middleware` (`terp.core` is not arch-scanned); the
`no_adhoc_middleware` rule stays the build-time pair, forbidding ad-hoc middleware
only where it should be (app / module code) now that a sanctioned composition path
exists. An app composes tenancy through the root:

```python
create_app(specs, middleware=[Middleware(TenantMiddleware, resolve_tenant=tenant_from_bearer)])
```

The kernel stays tenancy-agnostic: it never imports `TenantMiddleware`; the app
passes it in. The token → `tenant_from_bearer` → `TenantMiddleware` →
`TenantScopedService` chain (Decision 11) is unchanged — only its wiring moves
from arch-exempt test code to the sanctioned root.

## Consequences

- Tenancy (and any future capability middleware) is composed through the one
  sanctioned path; `no_adhoc_middleware` stays meaningful instead of contradicting
  the framework's own feature.
- App-supplied middleware runs innermost (inside the security stack), so security
  headers / CORS / rate-limit / body-size still wrap every response and the tenant
  context is bound right around the route.
- The tenancy end-to-end test now exercises the real `create_app(middleware=...)`
  seam rather than a test-only `add_middleware`, so the proof matches the shipped
  composition path.

## Alternatives considered

- **A focused `tenant_resolver=` parameter** that has `create_app` install
  `TenantMiddleware` itself. Rejected: it forces `terp.core` to import the tenancy
  capability, breaking the layer-0 boundary (ADR 0001) — the kernel must stay
  tenancy-agnostic. A generic `middleware=` keeps the capability out of the kernel.
- **App middleware outermost** (via `add_middleware` after the security stack).
  Rejected: app middleware would wrap — and could short-circuit — the security
  controls; innermost keeps the security stack authoritative and is the correct
  place for a per-request context binding.
- **Relax `no_adhoc_middleware` to allow `add_middleware` in `main.py`.** Rejected:
  it reopens the scattered-middleware footgun the rule exists to prevent; a single
  composition seam is safer and greppable.
