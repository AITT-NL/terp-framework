# 0150 — A second factor the platform owns, and a protocol it does not invent

- **Status:** Accepted and implemented. `terp-cap-mfa` ships TOTP enrolment, verification
  and recovery codes; `build_login_router(second_factor=...)` consults it; the access
  token carries an RFC 8176 `amr` claim. Held by `tests/architecture/test_mfa.py`.
- **Date:** 2026-09-18
- **Relates:** [ADR 0031](0031-session-management-token-revocation-and-login-lockout.md)
  (the login this extends), [ADR 0058](0058-pluggable-sso-oidc.md) (the only second
  factor available until now, and somebody else's),
  [ADR 0076](0076-webhook-secret-sealing-jwt-rotation-audit-append-only-and-upload-sniffing.md)
  (the sealing shape this borrows), [ADR 0088](0088-service-principal-credentials.md)
  (why machine credentials are out of scope here)

---

## Context

Authentication was password-only. OIDC could delegate a second factor, but only to
somebody else's identity provider — so an application whose most dangerous surface is
reached by an ordinary administrator password had nothing to offer unless its customer
already ran an IdP. The surfaces that matter most are exactly the ones a rank plus a
named grant protect: the parameters and credential references that reach production
systems. Those accounts were single-factor.

## Decision

**A capability, not a core feature.** `terp-cap-mfa` owns two tables, a self-scoped
router and the algorithm. It declares **no** auto-discovery entry point: a second factor
is not something an application should acquire by installing a package, because the login
route has to consult it, and mounting enrolment in an app whose login ignores it would
publish a control that does nothing.

**TOTP on the standard library.** RFC 6238 is HMAC-SHA1 over a counter — about twenty
lines against `hmac` and `hashlib` — and the specification publishes **test vectors**, so
correctness is checkable rather than asserted. That is what made hand-rolling defensible
where it usually is not: the primitive is the standard library's, and the arithmetic
around it is pinned to the RFC's own table. A dependency would have bought nothing and
added a supply-chain edge every consumer inherits.

**The secret is sealed at rest**, under an MFA-specific HKDF label, in the shape ADR 0076
established for the webhook signing secret. The secret *is* the factor and is never
rotated by the person who owns it, so a plaintext leak hands over every enrolled account
silently — the victims' phones keep producing the codes the attacker now produces.
Unlike webhooks there is **no legacy-plaintext tolerance**: no row here predates the
control, so an unsealed value is a bug or a tampered row, not history.

**Enrolment is two steps.** A secret is issued and gates nothing until a code generated
from it comes back. A mis-scanned QR code treated as live is a lockout at the next login,
and that is the failure that makes an organisation turn the feature off.

**Recovery codes are issued with the enrolment**, shown once, stored as digests, single
use. A factor with no way back in is a way to lose an account, and the support process
that grows into that gap — "ring us and we will disable it" — is a social-engineering
surface weaker than the factor it rescues. For the same reason there is **no
administrative disable route**: an operator who can turn off somebody else's second
factor is the weakest link in the control.

A plain `sha256` is right for these and a slow KDF would be wrong: they are 80-bit
strings this module generated, so there is no dictionary to mount and nothing for a work
factor to buy.

**The token records how it was obtained.** `create_access_token(amr=...)` signs RFC 8176
`amr`, and a login that proved a second factor mints `("pwd", "otp")`. The claim is
omitted when empty rather than defaulted: a token minted without being told says nothing,
and reading that silence as "password" would invent a fact the signature does not carry.
This is what a later step-up decision reads.

## The deployment names itself

The issuer is the label an authenticator app prints beside the six digits, and it is the
only thing distinguishing one unlabelled row from another on a phone that holds five. The
framework cannot know it, so it does not guess: `configure_mfa_issuer()` is one
composition-root line, and an application that never calls it gets the framework's own
name rather than a blank.

It is configuration, never client data. The issuer is baked into the QR code a person
scans, so a caller who could set it could make their own enrolment appear in the victim's
authenticator app under the name of a system they trust. That is the reason it takes the
same module-level seam shape as the files capability's upload limit rather than becoming
a request parameter, and the reason a blank name is refused at the root instead of at the
first enrolment — a blank issuer scans cleanly and fails silently, months later, when
somebody has two of them.

## The protocol, and the shape not taken

The code rides on the **login body**. `POST /login` answers a typed `mfa_required` 401,
the client prompts, and posts the pair again with the code.

The familiar alternative is two round trips, where the password returns a short-lived
challenge credential exchanged for a session. It was considered and not taken, because
the challenge is **a second bearer token** — one more credential to mint, verify, expire,
revoke and leak, whose only job is to remember a password check from four seconds ago.
Re-posting the password costs the client nothing it has not already done, over the same
TLS connection, and saves the platform a credential type it would have to defend.

The cost is real and stated rather than hidden: an attacker **already holding a valid
password** learns from that refusal that the account has a second factor. They learn
nothing they could not learn by trying, but the response is distinguishable — and it has
to be, because a client that cannot tell a wrong password from a missing code has no way
to prompt for one, and showing the wrong message is how people conclude the feature is
broken.

## Consequences

**Nothing changes for an application that does not wire the seam.** `second_factor`
defaults to `None`, and a login route without it never asks for a code even if enrolment
rows exist.

**`LoginRequest` gains an optional `mfa_code`**, so both committed OpenAPI contracts and
the example client move. Additive, and the field is optional.

**Two tables and a migration**, so this is consumer-visible. The recovery-code reference
declares `CASCADE`, and the service *also* deletes the children explicitly: the cascade
only fires where the database enforces foreign keys, which SQLite does not by default, so
relying on it alone would leave live recovery codes behind on one backend and not
another. A disabled factor whose codes still authenticate is the worst failure available
here.

**The enrolment response carries a plaintext secret**, which is the one governed
exception this capability takes (`arch-allow-schemas-exclude-sensitive-fields`, budgeted
at one). An authenticator app cannot be enrolled without it; it is returned once, never
read back from the row, and no other DTO carries it.

**What is not here.** WebAuthn, and step-up re-authentication — a policy saying *this
module needs a fresh second factor*. The `amr` claim is the half of step-up that has to
exist first, and it does; the policy half is a separate decision about how a requirement
is declared and what a re-authentication costs a session. Machine credentials
(ADR 0088) are deliberately out of scope: a client-credentials grant has no human to
prompt, and a shared TOTP secret in a worker's environment is a second copy of the first
factor rather than a second factor.
