# 0058 - Pluggable SSO: an OIDC capability behind the auth seams

- **Status:** Accepted
- **Date:** 2026-07-02
- **Context phase:** the "Pluggable SSO providers (OIDC/SAML) — no vendor tenant baked
  in" control the design's §5.5 reserves, listed as deferred in the internal status
  review after ADR 0054.
- **Relates:** [ADR 0022](0022-role-model-agnostic-and-tenant-aware-login.md) (the
  login-builder seam pattern this mirrors),
  [ADR 0031](0031-session-management-token-revocation-and-login-lockout.md) (the token
  epoch every SSO-minted access token signs),
  [ADR 0054](0054-refresh-token-sessions.md) (the refresh-cookie machinery an SSO login
  reuses unchanged),
  [ADR 0013](0013-users-capability-and-identity-boundary.md) (the identity store the
  federated link rows live in),
  [ADR 0055](0055-secrets-sealing.md) (sealed client secrets),
  [ADR 0027](0027-packaged-migrations-per-package-histories.md) (the packaged identity
  migration for the new table).

---

## Context

Terp ships an email + password login (auth + identity, ADRs 0022/0031/0054). Enterprise
deployments authenticate against an IdP (Entra ID, Okta, Google, Keycloak, dex, ...) via
OIDC. The design reserves the seam but bakes in **no vendor tenant**: SSO must be an
opt-in capability, and the local email + password path must stay green throughout.

Constraints inherited from the platform:

- **Layering.** The protocol capability must not import the user store; identity
  resolution is an app-wired seam (the `authenticate` pattern).
- **Two-layer enforcement.** Fail-closed runtime controls paired with build-time tests.
- **One session story.** Whatever mints the session, revocation (ADR 0031), refresh
  (ADR 0054), `/me`, and `/logout` must keep working unchanged.

## Decision

1. **OIDC first, Authorization Code + PKCE only.** A new opt-in capability,
   `terp.capabilities.oidc` (`terp-cap-oidc`), implements the OpenID Connect
   Authorization Code flow with PKCE (S256). No implicit or hybrid flow is offered.
   SAML can later ship as a sibling capability behind the same identity seam.

2. **Multi-provider registry.** The app declares one `OIDCProviderConfig` per named
   provider (issuer, client id, client secret, redirect URI, scopes). Endpoints and
   signing keys come from the issuer's `/.well-known/openid-configuration` discovery
   document; the JWKS is fetched lazily, cached, and re-fetched once on an unknown
   `kid` (key rotation). Configs are validated at construction (fail-fast): scopes must
   include `openid`, and in production the issuer and redirect URI must be `https`.
   The redirect URI is the app's own **explicit allowlisted value** signed into every
   authorize request — deny-by-default, mirroring the CORS stance.

3. **Sealed client secrets.** A provider's `client_secret` may be a sealed
   `enc:v1:` value (ADR 0055). The capability never decrypts: a sealed secret requires
   an app-wired `secret_resolver` (the app's single allowlisted decrypt site); a sealed
   secret with no resolver is refused at construction (fail-closed).

4. **SPA-shaped endpoints, public policy.** The module mounts two routes behind an
   explicit `Policy.public` (like `/login`):
   - `GET /{provider}/authorize` returns the IdP authorization URL (JSON); the client
     navigates to it. `state`, `nonce`, and the PKCE verifier are generated server-side
     (from `secrets`) and held in a single-use, TTL-bounded state store.
   - `POST /{provider}/callback` takes `{code, state}` (the query params the IdP
     appended to the redirect URI, relayed by the client), consumes the state
     (single-use, expiring), exchanges the code, and validates the ID token.

5. **Full ID-token validation, fail-closed.** Signature against the discovered JWKS
   (asymmetric algorithms only — `alg=none`/HS* are never accepted), `iss`, `aud`,
   `exp`/`iat` with bounded clock skew, and an exact `nonce` match against the stored
   value. The discovery document's `issuer` must equal the configured issuer (IdP
   mix-up defense). Every validation failure is a uniform 401; the callback is guarded
   by the existing per-source `LoginThrottle` machinery.

6. **OIDC owns protocol, not users.** The capability's one identity seam is an
   app-wired `resolve_or_provision(session, OIDCClaims) -> Principal | None`. The
   identity capability backs it:
   - a new `identity_federated_identity` table links a user to `(issuer, subject)` —
     **never by email alone** (the account-takeover vector);
   - `User.hashed_password` becomes nullable so an SSO-only user holds no local
     password, and password login refuses such users;
   - JIT provisioning is **off by default**; when enabled it requires a verified email
     claim, creates the user at the lowest default rank, and refuses to auto-link when
     a user with that email already exists (linking is an explicit, audited act).

7. **Terp tokens out, IdP tokens discarded.** A successful callback mints a normal
   Terp session exactly as `/login` does: the access token signs the tenant
   (`tenant_resolver`) and the subject's current token epoch
   (`token_version_resolver`, ADR 0031), and the rotating refresh cookie is set via
   `refresh_issuer` (ADR 0054). The IdP's tokens are used once and never returned, so
   one revocation/refresh/logout story covers both auth paths.

## Consequences

- The email + password path is untouched; an app that never mounts the capability sees
  no change.
- The build-time half of the enforcement ships with the capability's tests: it is
  arch-scanned like every capability (`test_capability_arch`), the authorize URL is
  asserted to carry only code-flow + PKCE parameters, and no endpoint returns raw IdP
  tokens.
- Deferred: RP-initiated / back-channel logout, IdP-claim-to-role mapping (role stays
  store-owned), per-tenant provider configuration, a SAML capability, and a stub-IdP
  e2e flow in the dev workbench.
