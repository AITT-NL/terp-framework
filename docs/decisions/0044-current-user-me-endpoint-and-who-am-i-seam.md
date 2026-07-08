# 0044 - Current-user (`/me`) endpoint and the who-am-I resolver seam

- **Status:** Accepted
- **Date:** 2026-06-29
- **Context phase:** Phase 4 (frontend contract) follow-up
- **Relates:** [ADR 0013](0013-users-capability-and-identity-boundary.md) (the
  identity/users store boundary this reads behind), [ADR 0031](0031-session-management-token-revocation-and-login-lockout.md)
  (the revocable principal provider `/me` answers through), [ADR 0041](0041-frontend-contract-openapi-export-seam.md)
  (the OpenAPI export / drift gate this regenerates), [ADR 0004](0004-typed-principal-role.md) /
  [ADR 0022](0022-role-model-agnostic-and-tenant-aware-login.md) (role-model-agnostic; rank
  on the wire)

> ADR number 0043 was taken by a parallel jobs-seam decision; this follow-up is 0044.

---

## Context

Building the frontend contract (`@terp/contract`) surfaced that the `AuthSession`'s
`currentUser()` had no backend source. The exported OpenAPI (ADR 0041) had **no
current-user endpoint**, and the access token carries no email — only the subject id,
the role (name + rank), the tenant, and the token epoch. The one endpoint that exposes a
user's email, `GET /api/v1/users/{id}`, is **ADMIN-only** (ADR 0013), so a normal
signed-in user had no way to obtain their own identity.

The fallback — decoding the JWT in the browser — is the wrong default: it trusts
unverified, potentially **stale** claims and bypasses the ADR 0031 revocation re-check
(a deactivated / demoted user would still look signed-in until the token expired).

## Decision

### 1. A self-scoped `GET /api/v1/me` on the auth (session) surface

The auth capability gains `build_me_module` / `build_me_router`, a `CurrentUser` DTO, and
a `CurrentUserResolver` seam (`Callable[[Session, Principal], CurrentUser]`). The resolver
is **app-wired**, so auth never imports the user store — symmetric with the existing
`authenticate` / `tenant_resolver` / `token_version_resolver` / `revoke_sessions` seams.

It mounts as its **own** module (name `me`, so `/api/v1/me`) behind `Policy.default()`
(any authenticated caller): the public login module cannot host an authenticated route,
and module names must be unique, so `/auth/me` under the login router is not available.
The whole session contract — login, logout, **me** — now lives on the auth surface,
matching the frontend's `AuthSession` grouping (and auth already owns the paired
`AccessToken` DTO).

### 2. The resolver reports the **live** store, not the token's claims

`IdentityService.current_user` resolves `principal.id` to the live row and maps its
stored rank to a named role through the app's `PermissionModel`. So `/me` reflects the
database, and the wire carries both the numeric `role_rank` (the comparable primitive)
and a display `role_name`. Answered through the wired **revocable** provider (ADR 0031),
a deactivated / demoted / re-tenanted token is already rejected before the handler runs;
a vanished subject (only reachable behind the *stateless* provider) is rejected as
unauthenticated rather than rendered.

### 3. Self-scope is structural, so no new AST rule

The handler reads only `principal.id` and takes **no** id parameter, so there is no
object-level read of another subject to police — it rides the existing deny-by-default
guard (authentication) and the read-only-request binder (a safe method cannot write).
Consistent with ADR 0031's runtime/boot-only precedent, the behaviour is covered by
unit + end-to-end tests; the two-layer build-time-rule requirement targets cross-cutting
invariants, not every feature route.

## Consequences

- The frontend contract regenerates: `openapi.json` gains `/api/v1/me/` + the
  `CurrentUser` schema, `schema.d.ts` is regenerated, and `@terp/contract`'s `CurrentUser`
  is now **reused from the generated schema** (drift-proof, like `Credentials` /
  `AccessToken`) instead of hand-authored — so `AuthSession.currentUser()` has a real,
  server-validated source.
- auth owns the `CurrentUser` DTO (mirroring `AccessToken`); identity — which already
  depends on auth — gains the one-call `current_user` resolver the bundled stack wires
  (`build_me_module(_identity.current_user)`), dogfooded by the example app and shipped in
  the copier template.
- Role stays a numeric **rank** on the wire by design (role-model-agnostic, ADR 0004 /
  0022); `role_name` is a display convenience only, never an authorization input.
- No new table or migration (read-only over the existing `identity_user`). The example
  escape-hatch budget stays `{}`.
