# 0189 — Sealing and signing retire a key on their own clocks

- **Status:** Accepted and implemented. Amends
  [ADR 0076](0076-webhook-secret-sealing-jwt-rotation-audit-append-only-and-upload-sniffing.md)
  §2: `SECRET_KEY_FALLBACKS` stays verify-only, and a decrypt-only `SECRET_KEY_DECRYPT_FALLBACKS`
  joins it. Held by `tests/architecture/test_key_rotation.py` (both lists, the derivations, the
  verification window, the production refusals) and `tests/architecture/test_cli_reseal.py`
  (`terp secrets reseal`).
- **Date:** 2026-10-22
- **Relates:** [ADR 0055](0055-secrets-sealing.md) (sealed config, whose "a re-seal step
  accompanies a key rotation" this supplies), [ADR 0054](0054-refresh-token-sessions.md) (the
  keyed refresh digest, whose "rotating `SECRET_KEY` invalidates every outstanding refresh token"
  this withdraws), [ADR 0062](0062-production-deployment-profile.md) (the production profile the
  rotation runs in), [ADR 0180](0180-a-value-is-required-where-the-app-runs-that-way.md) (the
  manifest field the two lists do not carry)

---

## Context

`SECRET_KEY` does two kinds of work, and ADR 0076 §2 gave only one of them a way through a
rotation.

It **signs**. Access tokens are HS256 JWTs, and a refresh session is looked up by a digest keyed
on the secret (ADR 0054). A signature is short-lived: an access token lasts fifteen minutes from a
login, a refresh token at most `REFRESH_TOKEN_TTL_SECONDS` (seven days by default) before it must
be used. `SECRET_KEY_FALLBACKS` kept access tokens verifying across a rotation, but the refresh
lookup never read it, so a rotation still signed every user out at their next refresh.

It **seals**. Sealed config (ADR 0055), webhook signing secrets (ADR 0076 §1) and MFA enrolment
secrets are Fernet values under keys derived from the secret, one HKDF label each. A sealed value
lives as long as its row, and as long as every backup that holds the row. Each sealer opened under
the live key alone, so changing the key made all of them unreadable at once: sealed config
refused, every webhook delivery failed terminally, and every enrolled user was locked out at the
second factor.

Letting `SECRET_KEY_FALLBACKS` decrypt as well would have fixed the outage and tied the two
clocks together. A sealed value needs its old key until it has been re-sealed, and until no backup
that may be restored still holds it under that key: weeks, or months. A signing key should be
gone once the longest signature has expired: minutes, or days. A key that verifies can be used to
sign by whoever holds it, so one list would keep a usable signing key alive for as long as the
backups need the sealing key.

Two smaller gaps sat beside it. Nothing could re-seal: ADR 0055 named the step and no command
existed. And one key did several jobs directly: every sealer derived its own key, but access
tokens were signed with `SECRET_KEY` itself, the same secret every derivation starts from.

## Decision

### 1. Every use of the key, classified

| Use | Kind | Key | Through a rotation |
|---|---|---|---|
| Access tokens (`terp-cap-auth`) | signature | HKDF label `terp.capabilities.auth.access-token.v1` (new) | verify-only, 15 minutes from `iat` |
| Refresh-session digest (`terp-cap-auth`, `terp-cap-identity`) | keyed lookup | SHA-256 of `terp.refresh-token.v1:` and the key (ADR 0054, unchanged) | verify-only, until the row's own expiry |
| Sealed config (`terp.core.secrets`) | encryption at rest | HKDF label `terp.core.secrets.config-seal.v1` | decrypt-only, until re-sealed |
| Webhook signing secrets (`terp-cap-webhooks`) | encryption at rest | HKDF label `terp.capabilities.webhooks.secret-seal.v1` | decrypt-only, until re-sealed |
| MFA enrolment secrets (`terp-cap-mfa`) | encryption at rest | HKDF label `terp.capabilities.mfa.totp-seal.v1` | decrypt-only, until re-sealed |

Nothing else reads the key. The OIDC state and PKCE verifier, realtime tickets, service-account
secrets (Argon2 hashes), MFA recovery codes (unkeyed digests), the idempotency fingerprint and the
webhook delivery signature (keyed by each subscription's own secret) take nothing from it. An OIDC
client secret is sealed config.

### 2. Two lists, and each does one job

`SECRET_KEY_FALLBACKS` **verifies** access tokens and finds refresh sessions, and never decrypts.
`SECRET_KEY_DECRYPT_FALLBACKS` (new) **decrypts** every sealed value, and never verifies. Nothing
is ever signed or sealed with an entry of either: signing and sealing use `SECRET_KEY` alone. A
rotation puts the old key in both lists, and the two come out at different times.

Both lists are read comma-separated, the shape a deploy tool writes into an env file, or as the
JSON list ADR 0076 documented. In production the boot is refused, inside the settings object's one
"Insecure production configuration" message, when an entry of either list is weak (a placeholder,
or under 32 characters), is `SECRET_KEY` itself (the new key was never set), or repeats an earlier
entry. The entry is named by its position and never by its value, and the settings object no
longer echoes refused input at all (`hide_input_in_errors`): Pydantic printed a shortened copy
beside each error, which for a list of keys is most of a key and for a refused `DATABASE_URL` is
its password.

### 3. A signature under a retired key lives out its own lifetime, and no longer

Access tokens are signed with a key derived from `SECRET_KEY` (`derive_key`, HKDF-SHA256 under
the label above), so the signing key is no longer the secret every other use derives from. Every
other key only verifies: the raw `SECRET_KEY`, which signed every token before this decision, so an
upgrade signs nobody out; and each `SECRET_KEY_FALLBACKS` entry in both forms. Under any of them a
token is honoured only within `FALLBACK_VERIFY_WINDOW` of its `iat` — fifteen minutes, the lifetime
a login gives a token — whatever `exp` it carries. When the access-token half of a fallback is
dead is therefore a number the framework enforces, including for a token an app minted itself with
a longer lifetime.

A refresh session is looked up under the current key's digest and then each fallback's. The row it
finds carries its own server-side expiry, at most `REFRESH_TOKEN_TTL_SECONDS` after it was minted,
and the rotation that consumes it stores the successor under the current key. Once that idle
lifetime has passed since the flip, no live session is stored under a fallback.

So the longest signature lifetime, after which `SECRET_KEY_FALLBACKS` can be dropped, is
`REFRESH_TOKEN_TTL_SECONDS` for an app that issues refresh sessions and fifteen minutes for one
that does not. Dropping it sooner loses no data; it signs out the sessions still on the old key.

The window bounds a token's life, not a forgery: whoever holds a listed key can sign a token with
a fresh `iat`. A key believed to have leaked therefore goes in `SECRET_KEY_DECRYPT_FALLBACKS` only.

### 4. A sealed value opens under a retired key until it is re-sealed

`SealingDomain` (`terp.core`) owns the rule for every sealer: seal under `SECRET_KEY` alone; open
under `SECRET_KEY`, then each `SECRET_KEY_DECRYPT_FALLBACKS` entry. The three sealers are domains
now and keep their labels, their `enc:v1:` format, their typed errors and their legacy policies.
`derive_key` is byte for byte the HKDF they already used, so every value sealed before this
decision opens unchanged; the upgrade is not a rotation.

Building a domain registers it. A second domain with a name or a label already taken is refused,
because one label must mean one domain, and because a second domain on the config label would be a
way round `decrypt_config`'s single call site. For the same reason the registry hands out names,
never domains.

### 5. `terp secrets reseal`

The command walks every string column of every table the app maps, after importing every declared
package's models so a capability that is installed but no longer wired is not skipped. Each value in
the `enc:v1:` format goes to `check_sealed_value`, which names the domain and the key that open it
and, when that key is a fallback, hands back the value re-sealed under `SECRET_KEY`; the plaintext
never reaches the command. What needed a fallback is rewritten.

- **One transaction per table.** A table that cannot be written rolls back whole and is reported;
  the others keep their re-seal.
- **Compare-and-swap per value.** The update matches the value it read, so one the running app
  rewrote meanwhile is never overwritten; it is reported, and the next run judges it.
- **Nothing else moves.** A re-seal changes no value, only its key, so it writes no audit record,
  pins every `onupdate` column (`updated_at`) to itself and leaves the version counter alone.
- **Refused while a migration is pending**, by the app's own boot guard: it rewrites rows through
  the schema this code maps.
- **Safe twice**: a value already under `SECRET_KEY` is left alone. `--check` only counts, and
  `--format json` is for a deploy tool.

It exits 0 only when every sealed value it found opens under `SECRET_KEY` and every table was read;
1 when something still needs a fallback, opens under no configured key, changed mid-run or sat in a
table that failed; 2 when it refused to run.

### 6. The template declares both lists

The template's `environment.schema.json` declares both as `"format": "secret"`, grouped as key
rotation, with no `requiredIn`: they are empty outside a rotation and required nowhere.
`.app.env.example` lists both with empty values. That is the seam a deploy tool sets them through.

### 7. The rotation procedure

1. Put the old key in **both** lists and the new key in `SECRET_KEY`. Deploy.
2. Run `terp secrets reseal` where the app runs.
3. Drop `SECRET_KEY_DECRYPT_FALLBACKS` once the re-seal reports nothing left. Keep the old key in
   custody for as long as a backup sealed under it may be restored: restoring one means listing the
   key again and re-sealing.
4. Drop `SECRET_KEY_FALLBACKS` once the longest signature lifetime (§3) has passed since step 1.

## Consequences

- A key rotation breaks nothing: no session ends inside its window, no sealed value stops opening,
  and no webhook or second factor fails.
- Access tokens are signed with a derived key from this release on. A token signed with the raw key
  verifies for the rest of its fifteen minutes. Anything outside the app that verified its tokens
  with `SECRET_KEY` itself stops verifying new ones; it has to derive the same key, base64url-encoded
  — or, better, ask the app. A test that hand-signs a token with `SECRET_KEY` keeps passing while
  the token's `iat` is fresh.
- A token an app minted with a lifetime above fifteen minutes survives a rotation for fifteen
  minutes under the old key, not for its full lifetime.
- A refresh session survives a rotation; ADR 0054's corollary that a rotation ends every one is
  withdrawn.
- `terp-core` requires `pydantic-settings>=2.7`, the first release with `NoDecode`.
- A refused setting no longer prints its value, for every field of the settings object.
- The re-seal's reach is string columns of mapped tables. A sealed value nested inside a JSON
  document, or in a table no code maps any more, is not found and keeps the key it was sealed under.
  Audit snapshots redact credential-named fields, so they normally hold none.
- The raw-key verification of access tokens is retired in a later release. Until then it honours
  nothing that a holder of `SECRET_KEY` could not sign anyway.
- These are runtime controls, fail closed, verified by gate tests; no arch rule is added, because
  there is no module-authored surface to police (the ADR 0076 precedent), and the spec catalog is
  unchanged.

## Alternatives considered

- **One list that verifies and decrypts.** Simplest, and it keeps a usable signing key alive for as
  long as the backups need the sealing key: the coupling this decision exists to break.
- **Count the verification window from process start.** It bounds a forged token as well as a
  genuine one. It also reopens on every restart — a scale-out, a crash loop, an unrelated deploy
  that kept the list — and the framework has no other record of when a rotation happened. The
  `iat` bound, and keeping a leaked key out of the verify list, say the same with less mechanism.
- **An expiry date beside each entry.** It would bound forgery, at the price of a format a deploy
  tool must write and an operator must read correctly at 3am. The two dates it would carry are the
  ones §7 already gives.
- **A declared list of sealed columns instead of a scan.** The app's own `encrypt_config` columns are
  exactly the ones nobody remembers to declare, and a re-seal that misses one loses it when the
  fallback is dropped.
- **Move the refresh digest to HKDF as well.** Its key is already per use and versioned, and a new
  derivation would be a rotation of every live session for nothing in return.
