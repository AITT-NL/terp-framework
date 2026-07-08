# 0054 - Refresh-token sessions: rotating, reuse-detecting refresh tokens in an httpOnly cookie

- **Status:** Accepted
- **Date:** 2026-07-01
- **Context phase:** Phase 4 (frontend) production-readiness; the deferred
  refresh-rotation from ADR 0031, and finding **#4** of the 2026-07-01 frontend review
  ("no session survives a page reload").
- **Relates:** [ADR 0031](0031-session-management-token-revocation-and-login-lockout.md)
  (this is the **refresh-token rotation it explicitly deferred** — "the right long-term
  shape for very short access tokens ... can layer on later without changing the
  validator seam"; the per-user epoch is reused here as the family-kill signal),
  [ADR 0013](0013-users-capability-and-identity-boundary.md) (the identity read-store /
  users audited-write boundary the new table + revoke path follow),
  [ADR 0004](0004-typed-principal-role.md) (the stateless access token stays exactly as
  is — the refresh token is a *separate* credential),
  [ADR 0022](0022-role-model-agnostic-and-tenant-aware-login.md) (the login-builder seam
  pattern the `/refresh` seams mirror),
  [ADR 0005](0005-security-middleware-and-structured-logging.md) (the security-header /
  CORS surface this extends with the first cookie + `allow_credentials`),
  [ADR 0015](0015-runtime-write-guarded-session.md) (issue/rotate/revoke are guarded
  writes), [ADR 0027](0027-packaged-migrations-per-package-histories.md) (the packaged
  migration for the new table).

---

## Context

A Terp access token is a short-lived (15-minute, ADR 0031) HS256 bearer JWT. The React
client holds it **in memory only** (a `useRef`, never `localStorage`), so an XSS payload
cannot read or exfiltrate it — a deliberate, valuable posture. The cost is finding #4:
**a page reload drops the in-memory token, so the user is bounced to the login screen**,
and even without a reload the session dies after 15 minutes.

The naive fix — persist the access token in `localStorage` / `sessionStorage` — is a
**security regression**: it re-exposes the token to XSS exfiltration (undoing the posture
above) and buys only the token's remaining < 15 minutes, because the backend has **no
re-authentication path**: login returns just `{ access_token }`, there is no refresh
token and no cookie session anywhere in the stack today.

The correct shape is the one ADR 0031 named and deferred: a **rotating refresh token**,
delivered in an **httpOnly cookie** the browser JS cannot read, exchanged at a new
`/auth/refresh` endpoint for a fresh access token. This keeps the access token in memory
(XSS-safe) *and* lets the session survive a reload and outlive 15 minutes — without ever
putting a JS-readable long-lived credential in the page.

Constraints inherited from the platform:

- **Layering.** Auth owns token mechanics and **must not import identity/users**; the
  store operations are app-wired seams (the `authenticate` / `token_version_resolver` /
  `revoke_sessions` pattern). The refresh store must follow the same rule.
- **Secure by default.** The bundled/example stack must get the secure behaviour with no
  security wiring of the builder's own, and a misconfiguration should fail **closed**
  (ADR 0006), boot-time where the shape allows.
- **Two-layer enforcement.** As ADR 0031 established, session mechanics live entirely in
  framework capabilities, so **no `terp.arch` AST rule applies**; the second layer is a
  boot/construction-time fail-closed guard plus the runtime protocol, backed by tests.

## Decision

Add **rotating, reuse-detecting refresh tokens** carried in an httpOnly cookie, exchanged
at `POST /api/v1/auth/refresh`, with the access token unchanged (still a 15-minute bearer
held in client memory). Nine parts:

### 1. The refresh token is opaque, high-entropy, and stored hashed (not a JWT)

- A refresh token is **256 bits of `secrets.token_urlsafe` randomness**, not a JWT. It
  carries no claims; its only meaning is "row *N* in the refresh-token table is still
  live." Opaque + stored is what makes it **individually revocable** (a JWT is not,
  without a store anyway).
- It is stored as a **keyed HMAC-SHA256 digest** (unique-indexed), the HMAC key derived
  from the app `SECRET_KEY` with domain separation (`HKDF`/`SHA256("terp.refresh-token.v1"
  ‖ SECRET_KEY)`). Keying ("peppering") means a **database leak alone cannot use or even
  confirm a token** — an attacker also needs the app secret. A slow salted KDF (Argon2, our
  *password* hash) is deliberately **not** used: the token is already 256-bit high-entropy
  (no brute-force/rainbow risk), and a *deterministic* keyed digest is what lets `/refresh`
  **look the row up in one indexed read**. The raw token is returned to the browser exactly
  once (in the `Set-Cookie`) and never persisted server-side.

### 2. An httpOnly cookie the page JS cannot read; the access token stays in memory

- `/login` and `/refresh` set `Set-Cookie: <name>=<raw token>` with
  **`HttpOnly; Secure; SameSite=Strict; Path=/api/v1/auth`**. `HttpOnly` keeps it out of
  `document.cookie` (XSS-unreadable); `SameSite=Strict` means no cross-site request ever
  carries it (the strongest CSRF stance); `Path=/api/v1/auth` means the browser sends it
  **only** to the auth endpoints (`/login`, `/logout`, `/refresh`) — not to `/me` or any
  data route — minimising both exposure and CSRF surface.
- The **access token is unchanged**: still returned in the response *body* and held in the
  client's `useRef`. XSS posture is identical to today for the access token; the *only*
  new persisted credential is the refresh token, and it is unreadable by JS.

### 3. `POST /api/v1/auth/refresh` — the re-authentication path

- Reads the refresh cookie (no `Authorization` header — this is how you *get* an access
  token), validates it, **rotates** it (§4), sets the new cookie, and returns a fresh
  `{ access_token }` in the body. A missing/invalid/expired/revoked cookie → **401**
  (fail-closed), which the client treats as "not signed in."
- It is mounted `Policy.public` (like `/login`) because it must be reachable without a
  bearer, but it is **not** unauthenticated: the refresh cookie *is* the credential.

### 4. Rotation with reuse-detection (the theft control)

- Each **login** opens a refresh-token **family** (a `family_id`). Every `/refresh`
  **rotates**: the presented token is marked `used`/`revoked` and a **new** token in the
  same family is issued. A refresh token is therefore single-use.
- **Reuse detection:** presenting a token that is already `used`/`revoked` (i.e. a stolen
  copy replayed after the legitimate client already rotated) revokes the **entire
  family** — every outstanding refresh token for that login — forcing a full re-login,
  and the event is surfaced to operators as a structured `refresh_token_reuse_detected`
  warning. This is fail-closed: an ambiguous/attacked state ends the session rather than
  trusting it.
- **Benign-race grace:** browser tabs share the cookie jar, so two tabs (or a client
  retry after a lost response) can legitimately present the same token near-simultaneously.
  A token spent within the last `REFRESH_ROTATION_GRACE_SECONDS` (default 60s) therefore
  rotates into a fresh successor instead of tripping the theft signal; only a replay
  *outside* the window (or of a revoked token) kills the family. Set it to `0` to disable
  the grace entirely.
- Each token has a per-token TTL and the family has an **absolute lifetime** (default 14
  days); past either, `/refresh` fails and the user logs in again.
  `RefreshTokenService.purge_expired` deletes rows whose family lifetime has passed (spent
  rows inside a live family are kept — they are reuse-detection's tripwire); run it from a
  scheduled job to bound table growth.

### 5. A new `identity_refresh_token` table, behind app-wired seams

- Table (co-located with `identity_user`, same packaged migration tree, ADR 0027):
  `id`, `user_id`, `family_id`, `token_hash` (unique-indexed), `expires_at`,
  `created_at`, `used_at`, `revoked_at`. It is append-mostly session state, not a domain
  aggregate.
- Auth stays store-agnostic via **three new optional seams** on the login/refresh
  builders — `RefreshIssuer`, `RefreshRotator`, `PrincipalResolver` — wired at the
  composition root to identity methods, exactly like `token_version_resolver` /
  `revoke_sessions` (the family *revoker* is a fourth seam on `UsersService`, see §6).
  Auth gains **no import of identity**; when the seams are absent the refresh endpoint is
  simply not mounted (backward-compatible, like `/logout` today). Wiring the refresh
  seams also **requires `revoke_sessions`** — without a server-side revoker `/logout`
  could only drop the cookie while the family stayed live, so that shape is refused at
  construction — and the configured `REFRESH_COOKIE_PATH` must match the module's mount
  prefix (a cookie the browser never sends to `/refresh` would make refresh silently
  never work).

### 6. Revocation reuses the existing chokepoint

- `UsersService.revoke_sessions` (already called on logout, deactivate, demote,
  email/tenant change, password reset — ADR 0031) **also revokes the user's refresh-token
  families** (an app-wired `refresh_revoker` seam, so `users` gains no hard dependency on
  the refresh store). So one audited write kills *both* the access-token epoch **and** every
  refresh token: a deactivated / logged-out user cannot refresh either. As defense in depth,
  **`/refresh` itself re-checks the subject is active and the family is live** before minting
  — so even a race cannot let a revoked session refresh into a fresh token. `/logout`
  additionally clears the cookie (`Set-Cookie` with `Max-Age=0`).

### 7. Login issues the first refresh token

- `build_login_router`, when the refresh seams are wired, sets the initial refresh cookie
  alongside the existing `{ access_token }` body. No new endpoint for login; the cookie is
  additive.

### 8. Frontend: silent refresh on boot + refresh-on-401

- **Boot:** `TerpProvider` calls `POST /auth/refresh` once on mount. Success → set the
  access token in memory + load `/me` → **the session survives the reload**. Failure →
  stay signed out. The access token is never read from or written to web storage.
- **Mid-session:** `createAuthClient`'s response path becomes "on 401, try `/refresh`
  **once**; on success replay the original request with the new access token; on failure
  clear the session and fall back to login." This **refines finding #2's interceptor**:
  an *expired* access token now refreshes transparently, while a *revoked* session (where
  refresh also fails) still bounces to login.
- The client is created with **`credentials: "include"`** so the cookie flows; nothing
  else in app code changes.

### 9. CORS / CSRF (the first cookie in the stack)

- A cross-origin SPA sending a cookie requires **`allow_credentials=true` with a specific
  echoed `Origin`** (never `*`); this is a documented deployment requirement on
  `BACKEND_CORS_ORIGINS` (ADR 0005's CORS surface).
- **CSRF:** the refresh cookie is `SameSite=Strict` + `Path`-scoped to `/auth`, and the
  access token is returned in the **body** (which cross-site JS cannot read, thanks to
  CORS). So a forged cross-site `/refresh` cannot even send the cookie, let alone read the
  minted access token. A `SameSite=None` (cross-site SPA) deployment is possible by setting
  `REFRESH_COOKIE_SAMESITE="none"` (with `Secure` enforced by the production guardrail),
  but then relies on the body-only access token + a double-submit CSRF token (noted as the
  hardening that pairs with `None`).

### Settings (typed, `local`-safe defaults)

New `Settings` fields (pydantic-settings, ADR 0005 config): `REFRESH_TOKEN_TTL_SECONDS`
(per-token idle, default 7d), `REFRESH_FAMILY_TTL_SECONDS` (absolute session cap, default
14d), `REFRESH_ROTATION_GRACE_SECONDS` (benign-race replay window, default 60s),
`REFRESH_COOKIE_NAME`, `REFRESH_COOKIE_PATH`, `REFRESH_COOKIE_SAMESITE` (`strict` default),
`REFRESH_COOKIE_SECURE` (default on outside `local`). The production guardrail (config's
`_enforce_production_guardrails`) **refuses to boot** if `REFRESH_COOKIE_SECURE` is off or
`SameSite=None` without `Secure` in production. No secret material is added — the token
entropy comes from `secrets.token_urlsafe` and the digest key is derived from the existing
`SECRET_KEY`. A corollary: **rotating `SECRET_KEY` invalidates every outstanding refresh
token** (their stored digests are keyed by it) — a fail-closed property to plan for when
rotating the secret.

### Two-layer enforcement

- **Runtime (fail-closed):** invalid/expired/revoked/reused refresh → 401 + family revoke;
  the epoch + refresh revoke share the audited `revoke_sessions` write.
- **Construction/boot-time:** the login builder is **all-or-nothing** — wiring some but not
  all refresh seams (issuer / rotator / principal-resolver) raises at *construction* time,
  wiring them without `revoke_sessions` (a logout that would not log out) raises too, a
  `REFRESH_COOKIE_PATH` that diverges from the module's mount prefix is refused, and an
  opt-in `require_refresh=True` demands the seams are present — so a half-wired or
  silently-disabled refresh path is a misconfiguration caught at composition time, never a
  silent production regression (mirroring `require_token_revocation`, ADR 0031).
- **Tests:** backend protocol tests (rotate, single-use, reuse-detection family kill,
  expiry, logout/deactivate revoke, cookie flags) at 100% coverage, plus a conformance
  spec asserting **a reloaded page stays signed in** and a revoked session still cannot
  refresh. Per ADR 0031/0006, no AST rule applies (framework mechanics, no authored
  pattern to police).

## Consequences

- **The session survives a reload and outlives 15 minutes** — the UX goal — with the
  access token **still never in JS-readable storage**. The only persisted credential is an
  httpOnly, path-scoped, rotating cookie.
- **Theft is detected and contained**: a replayed refresh token (outside the benign-race
  grace window) kills the whole family and logs a `refresh_token_reuse_detected` warning.
- **Layering holds**: auth gains no identity import; the store + revoke are app-wired
  seams; the access token and `Principal` are unchanged (ADR 0004).
- **Secure-by-default**: the example/bundled stack wires the seams and ships
  `require_refresh=True`; a stateless, no-refresh deployment stays possible but is
  the explicit, advanced choice.
- **New surface**: one new table + migration, one new endpoint, the first cookie (so CORS
  must allow credentials), and a small per-refresh cost (one indexed lookup + one write,
  once per access-token lifetime, not per request). Table growth is bounded by running
  `RefreshTokenService.purge_expired` from a scheduled job.
- **Backward compatible**: no refresh seams wired → no `/refresh`, no cookie, today's
  behaviour exactly.

## Alternatives considered

- **Persist the access token in `localStorage`/`sessionStorage`.** Rejected — re-exposes
  the token to XSS exfiltration (undoes the deliberate in-memory posture) for only a
  < 15-minute payoff, and still dies at the TTL. This is the anti-pattern the whole ADR
  exists to avoid.
- **A JWT refresh token.** Rejected — a self-contained refresh JWT is not individually
  revocable without a store anyway, so it buys nothing over an opaque stored token while
  making reuse-detection harder. Opaque + hashed row is simpler and revocable.
- **Longer-lived access token (e.g. hours).** Rejected — widens the stale-authorization
  window that ADR 0031 deliberately narrowed to 15 minutes; refresh rotation gets long
  *sessions* without long *tokens*.
- **Put the access token itself in a cookie (cookie-session).** Rejected — that sends an
  auth credential on *every* API request → full CSRF surface everywhere and couples auth
  to cookies. Our design keeps the access token a body/memory bearer and scopes the
  refresh cookie to `/auth` only.
- **Silent refresh via hidden iframe / third-party IdP.** Rejected — heavyweight and
  aimed at cross-origin OAuth; we own the identity provider, so a first-party `/refresh`
  cookie is simpler and stricter.
- **A dedicated `sessions` capability.** Deferred — the refresh table is auth-store state
  that belongs with `identity_user` (same boundary, same migration tree, same
  `revoke_sessions` chokepoint); a separate capability adds a package and wiring for no
  boundary benefit today. It can be extracted later without changing the seams.
