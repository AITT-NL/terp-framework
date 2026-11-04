# Authentication snapshots and session transitions

Token minting keeps the authority and revocation epoch that were read together during
authentication. A later epoch cannot be combined with an earlier role. Password login,
refresh, OIDC login and service credentials use the same check.

An authenticator wired with `token_version_resolver` or
`service_token_version_resolver` now returns `AuthenticatedPrincipal`, exported from
`terp.capabilities.auth`. Its `id`, `role`, `kind` and `token_version` come from the
same authenticated record snapshot. The bundled identity and service-account services
already return this value. The resolver verifies the live record against that snapshot;
an intervening demotion, credential change or revocation returns the normal 401 refusal.
Custom stateless authenticators without an epoch resolver may still return `Principal`.
An epoch-aware custom authenticator returning an ordinary `Principal` is refused.

The capture must precede any work that can refresh the identity record. Reading an epoch
after the password has been verified and copying it onto an old principal recreates the
race. A token issued just before a later revocation keeps its old epoch and is rejected
by the normal live token validator; applications must retain that validator.

Refresh issuers now accept the keyword `token_version`, containing the authenticated
epoch. Custom refresh stores must persist that epoch on the family and every rotated
successor, return it in `RefreshRotation.token_version`, and refuse a family whose
epoch no longer matches its subject. The refresh route also compares the rotation's epoch
with the newly resolved principal, covering a revocation between rotation and resolution.
`RefreshTokenService.issue` implements this contract. Its optional epoch argument remains
available for pre-existing direct store callers, but every framework login/SSO route
supplies it; custom login flows should do the same.

Run identity migration `0c8d9e2f4b71` before deploying the new identity model. The added
`identity_refresh_token.token_version` column is nullable for an additive rollout.
Pre-upgrade families retain their existing lifetime and are bound to the active user's
current epoch when first rotated. That captured epoch accompanies the successor and
principal check, so a concurrent revocation still refuses the refresh. A custom rotator
returning `RefreshRotation` without an epoch is refused. Newly authenticated families
always carry an epoch. Complete the
rollout of all API workers to enforce the new issuance contract everywhere.

Refresh-enabled login composition now also requires a `refresh_revoker` callback:

```python
refresh_issuer=refresh_tokens.issue,
refresh_rotator=refresh_tokens.rotate,
refresh_revoker=refresh_tokens.revoke_presented,
```

The revoker accepts `(session, raw_cookie)` and revokes that cookie's entire family
without minting a successor. A spent or expired ancestor still identifies its family;
unknown cookies do nothing. Cookie-only logout revokes this family, including successors
held by other tabs, and clears the browser cookie. It leaves independent families alone.
When a valid bearer is also presented, the existing `revoke_sessions` seam additionally
revokes the subject's access epoch and all refresh families. Cookie-only logout does not
invalidate a separately held access token, which remains bounded by its access lifetime.

OIDC authorization now sets a short-lived HttpOnly transaction cookie and requires it
on the callback. Its value is bound to the issued state, it is host-only, and secure
deployments use a `__Host-` name with `Secure`, `Path=/` and `SameSite=Lax` (or `None`
when the refresh-cookie configuration explicitly requires cross-site requests). Separate
flows have separate names, so starting a second tab does not overwrite the first flow.
Successful callbacks delete the transaction cookie; abandoned flows expire. Authorization
and callback responses are not cacheable. API clients implementing this browser flow
must preserve cookies between `/authorize` and `/callback`; transferring the URL to a
different browser is refused even when its code, state and nonce are valid.
