# 0076 — Webhook secret sealing, JWT rotation + `aud`/`iss`, audit append-only triggers, and upload magic-byte sniffing

- **Status:** Accepted
- **Date:** 2026-07-06
- **Relates:** [ADR 0075](0075-login-timing-proxy-identity-and-request-id-hardening.md)
  (whose deferred audit residuals this batch closes),
  [ADR 0031](0031-session-management-token-revocation-and-login-lockout.md) (the
  session-bound JWTs the new claims and rotation apply to),
  [ADR 0068](0068-files-content-type-allowlist.md) (the upload content-type
  allowlist the sniff layers on), and the webhooks and audit capability ADRs
  ([ADR 0051](0051-outbound-webhooks.md), [ADR 0007](0007-audit-auto-emit-and-the-audit-seam.md)).

---

## Context

ADR 0075 deferred four residuals from the same security audit — tracked, not
silently dropped:

- **Webhook signing secrets in plaintext at rest.** `webhook_subscription.secret`
  was stored verbatim: a database dump (backup, replica, misdirected query) hands
  an attacker the ability to forge deliveries every subscriber trusts.
- **JWTs with no `aud`/`iss` and no rotation story.** A token signed by any other
  system sharing the key material would verify here (confused deputy), and
  rotating `SECRET_KEY` invalidated every outstanding session at once — so
  operators would put rotation off.
- **Audit append-only in the app layer only.** `AuditService` refuses update and
  delete, but anything holding raw database credentials (a migration mishap, an
  operator session, SQL injection anywhere) could silently rewrite history.
- **Uploads trusted the declared content type.** The ADR 0068 allowlist checks
  the *label*, not the bytes: `evil.html` declared as `image/png` passes an
  image-only allowlist and is later served/parsed as whatever it really is.

## Decision

### 1. Webhook signing secrets sealed at rest

`terp-cap-webhooks` gains a sealing module: secrets are encrypted with Fernet
under a key derived (HKDF-SHA256) from `SECRET_KEY` with a purpose-bound info
string, and stored as `enc:v1:<token>`. `WebhookSubscriptionService.create` /
`update` seal at the service chokepoint (a router or programmatic caller cannot
write plaintext); the delivery worker unseals just before signing. An unsealable
secret (wrong `SECRET_KEY`, corrupt value) is a **terminal** delivery failure —
recorded, never retried, never signed with garbage. A value without the prefix
is treated as a legacy plaintext secret and passes through unchanged; the seal
ciphertext needs more room, so the column widens to 512 (input cap stays 256).

### 2. JWT `aud`/`iss` claims and `SECRET_KEY_FALLBACKS` rotation

Access tokens now sign and **require** `iss = "terp.auth"` and
`aud = "terp.api"` alongside the existing required claims — a token minted by
any other issuer or for any other audience is refused, even with shared key
material. `SECRET_KEY_FALLBACKS` (new core setting, default empty) lists
**verify-only** previous keys: verification tries `SECRET_KEY` first, then each
fallback, retrying only on an invalid signature; signing always uses
`SECRET_KEY`. Rotation is therefore: move the old key to the fallbacks, set the
new key, drop the fallback after the longest token lifetime. The production
guardrail rejects weak fallbacks exactly as it rejects a weak `SECRET_KEY`.

### 3. Audit append-only enforced by the database

A migration adds `BEFORE UPDATE` / `BEFORE DELETE` triggers on `audit_event`
that unconditionally raise (PostgreSQL plpgsql; SQLite `RAISE(ABORT)`), making
the append-only rule hold against **raw SQL** — not just against callers polite
enough to go through `AuditService`. Other dialects are a no-op (the shipped
lanes are PostgreSQL and SQLite).

### 4. Upload magic-byte sniffing

`FileService.store` peeks the first bytes of every upload after the allowlist
and profile checks: if the declared media type has a well-known file signature
(PNG, JPEG, GIF, WebP, BMP, TIFF, PDF, ZIP, GZIP) and the bytes lack it, the
upload is refused with a typed 415 (`content_type_mismatch`) before any byte
lands in the backend. The peeked head is replayed into the stream, so the
stored blob, its digest and its size cover the exact upload. Types without a
canonical signature (`text/*`, `application/json`, …) are not sniffed — the
control refuses proven mismatches, never guesses.

## Consequences

- A database dump no longer yields usable webhook signing secrets; pre-existing
  plaintext rows keep working (legacy passthrough) and re-seal on their next
  `update`.
- Outstanding pre-0076 access tokens are invalid (they lack `aud`/`iss`) — a
  one-time re-login, acceptable pre-release. From here on, `SECRET_KEY` rotates
  without mass logout via `SECRET_KEY_FALLBACKS`.
- `terp migrate upgrade` must run for the widened webhook column and the audit
  triggers; the audit trigger migration's `downgrade` restores mutability, so
  downgrade rights are effectively rewrite rights — protect them accordingly.
- Mislabeled uploads that previously stored fine now refuse with 415. This is
  always-on (no configuration knob): a deployment that wants the old behaviour
  has none, by design.
- These are runtime controls verified by gate tests (`tests/architecture/
  test_webhooks.py`, `test_capability_coverage.py`, `test_kernel_coverage.py`,
  `test_migrations_conformance.py`, `test_files.py`); no new arch rule — there
  is no module-authored surface to police, mirroring the ADR 0075 precedent.
- No residuals remain from the ADR 0075 deferred list.
