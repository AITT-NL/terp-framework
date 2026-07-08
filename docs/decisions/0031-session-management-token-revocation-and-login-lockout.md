# 0031 - Session management: token revocation, prompt `is_active` re-check, and login lockout

- **Status:** Accepted
- **Date:** 2026-06-28
- **Context phase:** Phase 2 (base profile), adversarial-review follow-ups (M4 + L3)
- **Relates:** [ADR 0014](0014-adversarial-review-hardening.md) (the adversarial
  review — findings **M4** "JWT has no revocation" and **L3** "no login-specific
  throttle/lockout"), [ADR 0004](0004-typed-principal-role.md) (the typed `Principal`
  role rebuilt from claims with no re-check — the thing M4 exploits),
  [ADR 0022](0022-role-model-agnostic-and-tenant-aware-login.md) (the login-builder
  seams this extends: `tenant_resolver` is the pattern the new resolvers mirror),
  [ADR 0013](0013-users-capability-and-identity-boundary.md) (the identity/users
  boundary — identity is the read-only auth store, users the audited write surface
  that bumps the epoch), [ADR 0016](0016-permission-in-policy-enforced-as-grant.md)
  (the `permission_enforcer` seam — the precedent for a fail-closed boot guard on a
  required capability), [ADR 0007](0007-audit-auto-emit-and-the-audit-seam.md) /
  [ADR 0005](0005-security-middleware-and-structured-logging.md) (the
  `DurableAuditSink` marker + `CorsPolicy.disabled(reason=…)` shapes this reuses).
  Findings **M4** / **L3** in
  [docs/internal/reviews/2026-06-24-adversarial-design-review.md](../internal/reviews/2026-06-24-adversarial-design-review.md).

---

## Context

A Terp access token is a self-contained, **irrevocable-for-its-TTL** HS256 JWT.
`decode_access_token` rebuilds the `Role` straight from the claims and `get_principal`
does **no** per-request store lookup (ADR 0004), so for up to the access-token lifetime
a token keeps whatever rank, tenant, and access it was minted with:

- **M4 — no revocation.** Deactivating a user (`users.set_active(False)`), demoting
  their role, resetting their password, or re-tenanting them does **not** invalidate
  their outstanding tokens. A demoted admin keeps admin for the TTL; a user whose
  password was just reset (e.g. after a compromise) keeps a live session on the old
  credential; `IdentityService.authenticate` refuses `is_active=False` **only at the
  next login**, never mid-session. There is no explicit logout either.
- **L3 — no login throttle.** The per-instance rate limiter is generic; there is no
  per-account failed-login counter, so credential stuffing against a single account is
  unthrottled.

Both are the residue of a stateless-token design. The fix must keep the platform's
layering (auth owns token mechanics and **must not import identity**; the validity
check is a seam the app wires), stay secure-by-default and typed, and ship as a
fail-closed runtime control with boot validation where the shape allows (ADR 0006).
Session management is **mostly runtime**: there is no agent-authored code pattern to
police, so — unlike soft-delete or ownership — **no `terp.arch` AST rule applies**; the
two layers are a runtime control plus a boot/construction-time fail-closed check.

## Decision

Adopt a **per-user token epoch (`token_version`)** as the revocation mechanism, checked
through a principal-seam validator the app wires to identity, and add a
**per-account login throttle** in the auth capability.

### 1. The epoch rides the token (auth, no identity import)

- `AccessTokenClaims` gains `token_version: int = 0`; `create_access_token(…,
  token_version=0)` signs a `tv` claim; `decode_access_token` reads it (a missing
  `tv` decodes to `0`, so a pre-existing token is treated as epoch 0).
- The default access TTL drops **30 → 15 minutes** — a short, sensible default that
  bounds the staleness window even for a deployment that does not wire revocation.

### 2. A validity seam on the principal provider (the runtime control)

- `TokenValidator = Callable[[Session, AccessTokenClaims], bool]` — returns whether a
  decoded token is still valid. Auth owns the type; the app wires the implementation,
  so **auth never imports identity** (symmetric with `authenticate` / `tenant_resolver`).
- `build_get_principal(token_validator=None)` returns the `get_principal` dependency.
  It decodes the bearer and, when a validator is wired, **rejects a token the validator
  fails** (→ `None` → 401), fail-closed. The provider now also depends on `SessionDep`
  so the validator can query the store (the guard already opens a session per request,
  so this adds no new cost on a guarded route). The bare `get_principal(request)` stays
  as the stateless, no-revocation provider for an app that deliberately chooses it.
- **`is_active` is re-checked here too**, not only at login: the wired validator folds
  the active-flag check and the epoch check into **one indexed primary-key lookup**.
- **Secure by default for the bundled stack.** Because the validator needs the store and
  auth must not import it, the wiring lives at the composition layer — but it is a *single
  call*: `IdentityService.principal_provider()` returns the validated
  `build_get_principal(token_validator=self.token_is_current)`. The example app (which a
  non-technical builder copies) wires that provider and sets
  `require_token_revocation=True` (§6), so the default bundled path is
  revocation-on; the stateless provider is the deliberate exception, not the default.

### 3. The store answers the validator + bumps the epoch (identity + users)

- `identity.User` gains `token_version: int` (FK-less plain column, default 0,
  `nullable=False`) with a packaged Alembic migration (ADR 0027); the migration adds a
  `server_default='0'` so the column is back-fillable on an existing table.
- `IdentityService.token_is_current(session, claims)` is the validator: the user exists,
  is active, **and** `user.token_version == claims.token_version`.
  `IdentityService.token_version_for(session, principal)` reads the current epoch so login
  can sign it (see §4).
- `users.UsersService` **bumps the epoch through the audited write chokepoint** on every
  security-relevant change — `set_active(active=False)` (deactivate), `update` (a role or
  email/tenant change), and `reset_password` — and exposes `revoke_sessions(session,
  user_id)` (bump + audited `_save`) for an explicit logout. Because the bump rides the
  same `_save`, invalidation is **audited and atomic** with the change that motivates it.

### 4. Login signs the current epoch + an explicit logout (auth login builders)

- `build_login_router` / `build_login_module` gain a `token_version_resolver:
  Callable[[Session, Principal], int] | None`. Login signs `token_version =
  resolver(session, principal)` (default `0`), so a freshly minted token carries the
  user's **current** epoch — without it, the first token issued after any bump would be
  instantly stale. (It is a separate seam from `tenant_resolver` to avoid breaking the
  ADR-0022 signature.)
- A `revoke_sessions: TokenRevoker | None` seam: when wired, the login module mounts
  `POST /logout`, which bumps the **caller's** epoch (idempotent, 204; an unauthenticated
  call is a no-op). Auth does not own the store, so the bump itself is the app-wired
  identity/users write.

### 5. Per-account login lockout (auth, the L3 control)

- `LoginThrottle` — an **in-memory, per-instance**, thread-safe counter keyed by login
  identifier (email): after `max_attempts` (default 5) failures inside a sliding `window`
  (default 15 min) the identifier is locked for a `lockout` window (default 15 min).
  `build_login_router` checks it **before** authenticating (a locked account raises the
  typed `AccountLockedError`, HTTP 429, fail-closed), records a failure on a bad
  credential, and clears the counter on success. It is **on by default**; turning it off
  is an explicit, reason-bearing `LoginThrottle.disabled(reason=…)` (mirroring
  `CorsPolicy.disabled` / `AuditPolicy.disabled`) — the construction-time fail-closed
  half. Per-instance is the documented starting point (like the existing rate limiter,
  L3); a shared store for correct multi-instance behavior is a later enhancement.

### 6. Boot validation (the second layer, where the shape allows)

`create_app(…, require_token_revocation=False)`: when an app sets it `True` but the
principal provider is **not** a revocation-enforcing one, boot fails closed
(`BootError`) — "a revocation-requiring config has no validator wired" is a
misconfiguration caught at composition time, never in production. `build_get_principal`
marks its provider through a core helper (`enforces_token_revocation(provider)`),
mirroring the `is_durable_audit_sink` marker the audit production guard already uses
(ADR 0007/0014). The kernel flag **defaults `False`** purely for backward compatibility
(the kernel cannot wire identity for you, and tests/minimal apps use the bare provider);
the **bundled stack treats revocation as the secure default** by having the example /
the shipped example app sets it `True` over the one-call validated provider. A short-TTL
stateless deployment remains possible, but it is now the explicit, advanced choice — a
builder who starts from the example composition gets prompt revocation without security
wiring of their own.

### Per-request cost (the documented tradeoff)

Prompt revocation costs **one indexed primary-key lookup per request** (the `User` row,
which also answers the `is_active` re-check — a single query, not two). An app that
prefers zero per-request store cost omits the validator and accepts the short (15-minute)
access-TTL window instead. The choice is explicit and per-deployment.

## Consequences

- A token stops working **mid-session** the moment its user is deactivated, demoted,
  re-tenanted (email change), has their password reset, or logs out — closing M4 — and a
  deactivated user is rejected at once, not at next login.
- Credential stuffing against one account is throttled and the account locks
  (`AccountLockedError`, 429) — closing L3.
- Layering holds: auth gains no import of identity; the validator, the epoch source, and
  the logout write are all app-wired seams (the `authenticate` / `tenant_resolver`
  pattern). The new persisted state is a single FK-less column on the existing `User`
  table — no new table.
- Backward compatible: `build_get_principal()` with no validator, `build_login_module`
  with no new resolvers, and an unset `require_token_revocation` all behave as before.
- Secure by default for the people who need it most: a non-technical builder copying the
  example composition gets prompt revocation, mid-session `is_active` enforcement, and
  login lockout with **zero** security wiring of their own — the bundled stack ships them
  on, and `require_token_revocation=True` means a future refactor that drops the validated
  provider fails the boot instead of silently regressing to stale tokens.
- The example app dogfoods the whole path end to end (validated provider via
  `IdentityService.principal_provider()`, epoch-signing login, `/logout`, the throttle,
  and `require_token_revocation=True`).

## Alternatives considered

- **Refresh-token rotation (short access token + a stored, rotating, revocable refresh
  token with reuse-detection).** Deferred. It is the right long-term shape for very
  short access tokens, but it needs a new persisted table, a rotation/reuse-detection
  protocol, and a new endpoint — more surface than M4 requires. The epoch already gives
  immediate, total per-user revocation; refresh rotation can layer on later without
  changing the validator seam.
- **A `jti` deny-list (per-token revocation).** Deferred. It needs a table (or cache) and
  a per-request membership check, and it revokes *individual* tokens — whereas the
  security events here (deactivate, demote, password reset) mean "kill **all** of this
  user's sessions", which a single epoch bump does in one write with no growing list to
  prune.
- **An epoch *timestamp* (`tokens_valid_after`) compared against the token `iat`.** It
  would avoid the `token_version_resolver` (the token already carries `iat`), but JWT
  `iat` is integer-seconds, so a token minted in the same second as a revocation is
  ambiguous, and time-based comparisons make the 100%-coverage tests clock-sensitive. The
  integer **counter** is exact and deterministic; the extra login resolver is a small,
  single-responsibility seam symmetric with `tenant_resolver`.
- **Re-fetch the full principal (role, tenant) from the store every request.** Rejected
  as the *default*: it makes every request a store read and re-opens the "is the bundled
  store the only store" coupling. The epoch check is the minimal signal — one column, one
  lookup — that answers "is this token still valid" without re-deriving authorization.
- **A `terp.arch` AST rule.** Not applicable: session management lives entirely in the
  framework capabilities (token mechanics, the validator, the throttle), with **no**
  module-authored code pattern to ban — so per ADR 0006 "where the shape allows", the
  second layer is the boot/construction-time guard (§5/§6), not a build-time AST rule.
