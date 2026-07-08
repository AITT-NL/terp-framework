# 0022 - Role-model-agnostic identity + a tenant-aware login seam

- **Status:** Accepted
- **Date:** 2026-06-25
- **Context phase:** Phase 2 (base profile), adversarial-review follow-ups
- **Relates:** [ADR 0014](0014-adversarial-review-hardening.md) (the adversarial
  review — finding **H7**), [ADR 0004](0004-typed-principal-role.md) (the typed
  `Principal` role — role-model-agnostic *at the kernel guard*),
  [ADR 0021](0021-create-app-middleware-seam.md) (the middleware seam that made
  tenancy composable), [ADR 0002](0002-control-plane-and-auditable-module-authority.md)
  (the control-plane `PermissionModel`). Finding **H7** in
  [docs/internal/reviews/2026-06-24-adversarial-design-review.md](../internal/reviews/2026-06-24-adversarial-design-review.md).

---

## Context

The bundled identity/login contradicted two headline claims:

1. **"Role-model-agnostic"** was true only at the kernel guard (ADR 0004).
   `IdentityService.authenticate` built `Principal(role=Roles(user.role))`, and
   `Roles` is the fixed three-tier `IntEnum` — so any stored rank outside
   `{10, 20, 30}` raised `ValueError` → 500. An app with a richer role ladder could
   not use the bundled login at all.
2. **"Multi-tenant by construction"** — `build_login_router` issued a token with no
   `tenant` claim, so `tenant_from_bearer` returned `None` and every
   `TenantScopedService` read was empty / write raised. With the middleware seam
   shipped (ADR 0021), the last gap was that the bundled login could not *issue* a
   tenant-bound token.

## Decision

1. **Resolve the role through the app's `PermissionModel`.**
   `IdentityService(permission_model=...)` (defaulting to `PermissionModel.default()`)
   resolves a user's stored rank with `permission_model.role_for_rank(user.role)`,
   returning the named `Role` the app's ladder registers. Any rank the model defines
   authenticates; the default keeps a three-tier app working with no wiring. A rank
   the model does *not* define fails closed (no token is minted for an unmodeled
   role) — the same failure mode as before, but now driven by the app's own model
   instead of a hard-coded enum.

2. **A `tenant_resolver` seam on the login builders.**
   `build_login_router(authenticate, *, tenant_resolver=None)` and
   `build_login_module(..., tenant_resolver=None)` accept an optional
   `LoginTenantResolver = Callable[[Session, Principal], uuid.UUID | None]`. When
   supplied, the authenticated principal is mapped to a tenant and that tenant is
   signed into the token's `tenant` claim — the same claim `TenantMiddleware` reads
   (ADR 0021). The auth capability stays agnostic about *how* a tenant is stored
   (symmetric with `TenantMiddleware`'s `resolve_tenant`); the app supplies the
   resolver.

The example wires `IdentityService(control_plane.permissions)`, so its login
resolves roles through the app's own ladder.

## Consequences

- The bundled login is genuinely role-model-agnostic end to end: a consumer-defined
  rank authenticates instead of 500ing.
- A multi-tenant app issues tenant-bound tokens through the bundled login via one
  optional kwarg — no login replacement, no fork of identity.
- Both additions are optional and backward-compatible: `IdentityService()` and
  `build_login_module(authenticate)` behave exactly as before.

**Update (2026-06-25, review hardening):** the example now *exercises* both halves
end to end — its `/auth/login` resolves a tenant from the user's email domain (via
the `tenant_resolver` seam) so a real login yields a usable tenant token for the
tenant-scoped `projects` module, and the bundled `users` admin DTOs take a role
**rank** (`int`) rather than the fixed `Roles` enum, so an admin can provision any
rank the app's model defines (an unmodeled rank fails closed at that user's login).

## Alternatives considered

- **Thread the tenant through the `Authenticator` return value** (the review's
  literal phrasing). Rejected: it changes the `Authenticator` contract (and
  `IdentityService.authenticate`'s signature) for every consumer. A separate
  `tenant_resolver` is single-responsibility (authenticate verifies credentials; the
  resolver maps principal → tenant) and non-breaking.
- **Add `tenant_id` to the bundled `User`.** Rejected as opinionated: not every app
  is multi-tenant, and the tenant may not live on the user row (it can come from the
  login domain or be selected post-login). The resolver seam leaves that to the app.
- **Catch the unmodeled-rank `ValueError` and return 401.** Rejected: an unmodeled
  rank is a server-side misconfiguration, not a bad credential; surfacing it as an
  internal error (logged) is more honest than masking it as "wrong password."
