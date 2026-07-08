# 0032 - Password strength policy (Tier-B), enforced at the credential boundary

- **Status:** Accepted
- **Date:** 2026-06-29
- **Context phase:** Phase 2 (base profile), cross-cutting-controls roadmap (the
  leading Tier-B gap)
- **Relates:** [ADR 0006](0006-cross-cutting-controls-and-opinionation-policy.md)
  (the Tier A/B/C ladder + the "quadruple" rule this control fills as a **Tier-B**
  item), [ADR 0005](0005-security-middleware-and-structured-logging.md) (the
  `SecurityConfig` registry on `ControlPlane` + `production_problems()` boot fail-fast
  this mirrors), [ADR 0007](0007-audit-auto-emit-and-the-audit-seam.md) /
  [ADR 0031](0031-session-management-token-revocation-and-login-lockout.md) (the
  `AuditPolicy.disabled(reason=…)` / `CorsPolicy.disabled` / `LoginThrottle.disabled`
  opt-out shape `PasswordPolicy.relaxed(reason=…)` reuses), [ADR 0013](0013-users-capability-and-identity-boundary.md)
  / [ADR 0022](0022-role-model-agnostic-and-tenant-aware-login.md) (the
  `users` audited write chokepoint + identity store this enforces at). Closes the
  [IMPLEMENTATION_PLAN §10](../internal/IMPLEMENTATION_PLAN.md) Tier-B "password policy"
  item.

---

## Context

A credential could be as weak as a single character: the only password control was a
`max_length` cap on the `UserProvision` / `UserPasswordReset` fields — a DoS guard, **not**
a strength rule. So "secure by default" did not extend to the one secret every account
hangs on. Password strength is **Tier-B** (ADR 0006): how long, how complex, which terms
to deny *varies by company*, so the framework owns the **shape** (a minimum length, a
character-class floor, a cheap common-password denylist) and the consumer owns the
**values** — never the shape.

Per ADR 0006 a control becomes framework-level only as the full **quadruple**: a typed
control-plane registry with a safe default, a fail-closed runtime control, a build-time
test, and a budgeted/justified escape hatch. The constraint is layering: `terp.core`
(layer 0) must not import a capability, but the credential write lives in the `users`
capability — so core owns the *seam* and the cap enforces it.

## Decision

Add a `PasswordPolicy` registry to the control plane with a safe default, enforce it
fail-closed at the credential write boundary, fail the production boot when it is
relaxed, and ship `PasswordPolicy.relaxed(reason=…)` as the justified opt-out.

### 1. The registry (safe default; consumer overrides values, not shape)

`terp.core.passwords.PasswordPolicy` (frozen) carries `min_length=12`,
`min_character_classes=2` (of lower/upper/digit/symbol), and a small denylist of
common/breached-shaped passwords. `PasswordPolicy.default()` is production-safe; a
consumer tightens the *values* (`PasswordPolicy(min_length=16, min_character_classes=3,
denylist=(…))`) but cannot change the shape. It is `ControlPlane.passwords`, defaulted so
existing apps boot unchanged. The default favours **length over forced complexity** (NIST
SP 800-63B), so a passphrase passes and only weak/short/common secrets are refused.

### 2. The runtime control — the service chokepoint, not the schema

`validate_password` enforces the active policy and raises a typed `WeakPasswordError`
(422, uniform envelope). It is called at the `UsersService` write chokepoint —
`create` (provision) and `reset_password` — which is **every** path a password is set
through; a future self-service change routes the same way. The `max_length` DoS cap stays
on the schema, never weakened.

**Schema vs. service — chose service.** Validating in a pydantic field-validator would
wrap the rejection in pydantic's own `ValidationError` → FastAPI's default 422, *not* the
uniform `{code, detail, request_id}` envelope (there is no `RequestValidationError`
handler). Enforcing one layer in, at the audited service chokepoint, raises a real
`AppError` so the rejection is the uniform `weak_password` envelope — consistent with
audit/ownership living at the same chokepoint. (The plan's "schema boundary" note is
corrected here: the *credential boundary* is the service.)

### 3. The boot control (the second layer, where the shape allows)

`create_app` installs the active policy (`configure_password_policy`) and, under
`ENVIRONMENT == "production"`, fails closed (`BootError`) if `passwords.production_problems()`
is non-empty — i.e. the policy is relaxed or its floor is below 8. A relaxed credential
posture is caught at composition time, never in production, mirroring the CORS / audit
fail-fast.

### 4. The escape hatch

`PasswordPolicy.relaxed(reason=…)` turns strength off (only the DoS cap remains) as an
explicit, greppable, reason-bearing opt-out — `CorsPolicy.disabled` / `AuditPolicy.disabled`
/ `LoginThrottle.disabled`. Production refuses it, so dropping the floor is deliberate.

### terp.arch vs. runtime/boot

No `terp.arch` AST rule applies. Like session management (ADR 0031), there is no
agent-authored code pattern to police: enforcement is the framework chokepoint plus the
registry, so the two layers are the fail-closed **runtime** check and the **boot** fail-fast
(the kernel suite is the build-time half). The escape-hatch budget is unaffected (no marker).

## Consequences

- A weak/short/common password is refused (422 `weak_password`) at provision and reset; a
  policy-passing passphrase is accepted, so the gate refuses values, not all writes.
- Layering holds: core owns the seam; the cap enforces it; core imports no capability.
- Backward compatible: `ControlPlane.passwords` defaults safe; the example dogfoods the
  default and `require_token_revocation` boot stays green.
- The example app proves it end to end: a weak provision/reset is rejected, a strong one
  accepted, over real HTTP.

## Alternatives considered

- **Hash-time enforcement (in `auth.hash_password`).** A true single chokepoint, but it
  validates every internal hash (test fixtures, seeds), widening blast radius, and 422 is
  a boundary concern, not a hashing one. The service boundary is precise.
- **A full breach-corpus (HIBP) check.** Deferred — a product concern (network/dataset)
  layered on the registry, not a kernel default.
- **A character-class maximum (force 3–4 classes).** Rejected as the default: NIST
  deprecates forced composition; length + a denylist is stronger and passphrase-friendly.
  A consumer may still raise `min_character_classes`.
