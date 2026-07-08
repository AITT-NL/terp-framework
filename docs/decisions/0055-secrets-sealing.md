# 0055 - Secrets sealed by default: `encrypt_config` / `mask_config` / `decrypt_config`

- **Status:** Accepted
- **Date:** 2026-07-02
- **Context phase:** Core substrate (design §5.4) — the last "still to carve"
  secrets item on the status tracker, and the client-readiness plan's
  minimal-path step **(c)** (secrets sealing before handling client
  credentials/config in production).
- **Relates:** [ADR 0006](0006-cross-cutting-controls-and-opinionation-policy.md)
  (the two-layer quadruple this control ships as),
  [ADR 0051](0051-outbound-webhooks.md) (which explicitly deferred at-rest secret
  sealing to "the §5.4 subsystem" — this ADR is that subsystem),
  [ADR 0033](0033-generic-enforcement-in-ci.md) (the generic backstops the new
  rule layers under), the escape-hatch budget ratchet (design §8 / ADR 0001
  Decision 10), which is the *allowlist mechanism* for the one decrypt site.

---

## Context

Design §5.4 ("Secrets sealed by default") calls for a first-class secrets helper —
`encrypt_config` / `mask_config` / `decrypt_config` — where `decrypt_config` may be
called from **exactly one allowlisted call site** and every other surface renders a
masked value, enforced by `test_decrypt_single_call_site`. The status tracker carried
it under "Core substrate still to carve", and ADR 0051 (webhooks) explicitly deferred
at-rest sealing to this subsystem. Until now an app had no sanctioned way to keep a
sealed configuration value (a third-party API key, a DSN, a signing secret) out of
logs, admin surfaces, and ad-hoc reads.

## Decision

**`terp.core.secrets`** ships the §5.4 subsystem as an ADR-0006 quadruple:

1. **`mask_config(value)`** — the only module-facing rendering of a sealed value: the
   constant `"****"`. The mask never varies with the value (no prefix, no suffix, not
   its length), so a masked surface is oracle-free.
2. **`encrypt_config(plaintext)`** — seals into the portable, versioned
   **`enc:v1:<token>`** format. The cipher is **Fernet** (AES128-CBC + HMAC-SHA256),
   keyed from the live `SECRET_KEY` through an **HKDF-SHA256** with a Terp-specific
   `info` label (`terp.core.secrets.config-seal.v1`), so the seal key is
   domain-separated from every other `SECRET_KEY` use (JWT signing, …). Sealing is
   safe to call anywhere.
3. **`decrypt_config(sealed)` — the fail-closed runtime chokepoint.** The composition
   root registers **exactly one** callable per process via
   `register_decrypt_call_site` (usable as a decorator; a second, different
   registration raises; re-registering the same callable is idempotent). Every
   decrypt checks the *caller's code object* against the registered site and raises
   the typed `SecretsError` (500, uniform envelope) on: no registered site, a caller
   other than the registered site, a value not in the sealed format, or a token that
   does not authenticate under the current `SECRET_KEY`.
4. **`no_adhoc_config_decrypt` — the build-time layer.** A new `terp.arch` rule flags
   any `decrypt_config(...)` call in scanned app/capability code, so the one
   sanctioned site is a justified, **budgeted** `# arch-allow-no-adhoc-config-decrypt`
   marker under the escape-hatch ratchet — the design's "allowlisted endpoint" is the
   governed opt-out mechanism the platform already trusts, greppable and ratcheted.
   `mask_config` / `encrypt_config` are freely usable. The rule is auto-surfaced in
   the generated `terp guide rules` and paired with its meta-test.

**Dependency posture.** The cipher comes from the `cryptography` package as an
**optional extra** — `terp-core[secrets]` (`cryptography>=48.0.1`, the advisory-clean
floor) — imported lazily inside the seam. An app that never seals config never loads
it; calling `encrypt_config` / `decrypt_config` without the extra raises a clear
`SecretsError` naming the extra. The kernel's default dependency set is unchanged
(fastapi / sqlmodel / pydantic-settings), preserving the minimal-kernel stance that
put `httpx` in the webhooks cap and `pwdlib` in auth.

**Enforcement summary (the quadruple):** runtime = the single-call-site allowlist
inside `decrypt_config` (fail closed on every path); build-time =
`no_adhoc_config_decrypt`; the kernel gate proves the runtime half in
`test_decrypt_single_call_site` (the design-§5.4 named test) plus the full failure
matrix in `tests/architecture/test_secrets.py`; docs = the generated rules surface.

## Consequences

- A sealed value can now live in config/rows and cross admin/read surfaces only as
  `"****"`; the decrypt surface cannot silently grow (a second site fails at runtime
  *and* is a budget bump in review).
- ADR 0051's deferred at-rest webhook-secret sealing can now build on this seam.
- Key rotation invalidates existing seals (the token authenticates under the current
  `SECRET_KEY` only); a re-seal step accompanies a key rotation. A future `enc:v2:`
  can coexist via the versioned prefix.
- The vendored mirror (`vendor/terp-core/`, ADR 0034) is refreshed byte-exact;
  `terp.core` stays at 100% coverage; the example app and its budget (`{}`) are
  untouched.
