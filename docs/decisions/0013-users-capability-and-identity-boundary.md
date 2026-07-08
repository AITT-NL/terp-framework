# 0013 - The users capability + the identity/users boundary

- **Status:** Accepted
- **Date:** 2026-06-24
- **Context phase:** Phase 2 (base profile), after `terp-cap-identity` (ADR 0001 Decision 7)
- **Relates:** [ADR 0001](0001-terp-namespace-and-kernel-scope.md) (Decision 7 —
  identity + entry-point discovery),
  [ADR 0007](0007-audit-auto-emit-and-the-audit-seam.md) (the audited write chokepoint)

---

## Context

The base profile (design §13, Phase 2) is core + auth + access + identity +
**users** + **projects**. `terp-cap-identity` (ADR D7) already ships a persisted
`User` store, an `IdentityService` (`create` / `authenticate` / `get_by_email`),
and — as a Phase-2 stand-in — a **read-only** admin `users` router (list + get)
mounted at `/api/v1/users` via entry-point discovery.

`terp-cap-users` is specified as the persisted administration surface for people
and accounts. That raised the boundary question: identity *already* persists
users, so what does `users` add, and how do the two relate without a second
`User` table or a collision on `/api/v1/users`?

## Decision

Adopt the **store / administration** split:

> **`identity` is the authentication-facing store; `users` is the administration
> surface over it.** There is one `User` table, shared by the login path and the
> admin surface.

1. **`terp-cap-identity` becomes an auth-only library capability.** It keeps the
   `User` model and an **authentication-only** `IdentityService` (`authenticate` /
   `get_by_email`) plus the `UserRead` DTO — but **drops its router, its
   `terp.capabilities` entry point, and every write method** (`create` / `update` /
   `delete`). It no longer subclasses `BaseService`, so it exposes **no mutation
   surface** at all: the only way to change a user is through `users`. It is
   imported directly to back the auth login flow. (Closing this side-door was a
   review finding — a public `IdentityService.create` would have bypassed both the
   `users` admin policy and, because it wrote with a raw `session.add`, the audit
   chokepoint.)

2. **`terp-cap-users` owns the administration surface.** It depends on
   `terp-cap-identity` (+ `terp-cap-auth`), imports the `User` model, and
   self-registers (`terp.capabilities` entry point) the admin router at
   `/api/v1/users`: **list · get · provision · edit (OCC) · deactivate ·
   reactivate · admin password-reset**. It is **admin-only** (`Policy` requires
   `ADMIN` for read and write). Every write routes through the audited
   `BaseService` `_save` chokepoint (so each administrative action lands an audit
   record), and passwords are hashed via `terp-cap-auth`.

3. **Deactivation over deletion.** A user is **deactivated** (`is_active=False`),
   never hard-deleted, so history/audit survive and `authenticate` already refuses
   an inactive user. There is no `DELETE /users/{id}`.

Entry-point discovery makes the swap seamless: removing identity's entry point and
adding users' entry point moves the `/api/v1/users` owner with **no
composition-root edit** (`create_app(discover_capabilities=True)`).

### Why this split (over the alternatives)

- **One store, no drift.** A second, independent user table in `users` (the
  rejected Option B) would duplicate the login store and inevitably drift. Sharing
  identity's `User` keeps a single source of truth.
- **One surface.** Keeping identity's read-only `/users` and bolting write
  operations onto a *different* prefix (the rejected Option C) splits the admin UX
  across two routes. A single `/api/v1/users` owned by `users` is cleaner.
- **Clean layering, already the norm.** `identity` answers "who may log in" (and is
  consumed by `auth`); `users` answers "administer the accounts" (and is consumed by
  admins). A capability depending on another capability is the established pattern —
  `identity` already imports `auth`.
- **Secure-by-default writes.** Routing the admin mutations through `BaseService`
  means provisioning, role changes, deactivation, and password resets are all
  audited with zero extra wiring (ADR 0007), and `deactivate`-over-`delete` keeps
  the trail intact.

### Generic administration boundary

Terp owns its user store, so `users` is a **real persisted administration
capability** over identity's table. It is authored generically: no external-API
coupling, no company-specific role lists, and no second source of truth for user
records.

## Consequences

- `terp-cap-identity` is now a library capability (no router, no entry point); the
  `/api/v1/users` route is owned by `terp-cap-users` with the full admin surface.
  The discovery test (`"users" in iter_capability_specs()`) still holds — the spec
  is now supplied by `users`.
- The example app dogfoods the administration surface end-to-end (provision /
  edit / deactivate / reactivate / reset-password, all admin-only and audited);
  the read paths it previously exercised on identity now exercise `users`.
- The base profile now lacks only **projects** (`terp-cap-projects`), the next
  Phase-2 capability.
- **Core hardening (review follow-up):** `BaseService._save` now maps a commit-time
  `IntegrityError` to a typed `ConflictError` (HTTP 409, raw detail in
  `log_context`, never serialised). So a duplicate-email provision — and any other
  unique / referential constraint violation across the whole framework — returns the
  uniform error envelope instead of a leaked 500. This is a framework-wide
  improvement that the `users` review surfaced, not a `users`-specific patch.

## Decision

Status: **Accepted** — `identity` is the auth-facing store (a library capability),
`users` is the admin administration surface over the shared `User` table
(self-registered, admin-only, audited writes, deactivate-over-delete). Gate: **247
passed, 100% line coverage**; the example app dogfoods the surface with an
escape-hatch budget of `{}`.
