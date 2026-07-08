# 0075 — Login timing equalization, trusted-proxy client identity, and request-id validation

- **Status:** Accepted
- **Date:** 2026-07-06
- **Relates:** [ADR 0031](0031-session-management-token-revocation-and-login-lockout.md)
  (the login throttle and session controls this batch's caller identity feeds),
  [ADR 0058](0058-pluggable-sso-oidc.md) (the OIDC callback throttle re-keyed here),
  [ADR 0005](0005-security-middleware-and-structured-logging.md) (the central
  middleware stack the new client-ip resolver joins), and the prior adversarial
  batches [ADR 0014](0014-adversarial-review-hardening.md) /
  [ADR 0073](0073-security-enforcement-batch-and-studio-hardening.md).

---

## Context

A security audit of the framework surfaced three runtime gaps that no existing
control covered:

- **Login timing user enumeration.** `IdentityService.authenticate` returned
  immediately for an unknown or inactive email and for an SSO-only account,
  while a known email cost a full Argon2 verification — a remote timing side
  channel that enumerates registered accounts (and reveals which are SSO-only).
- **Per-caller controls collapse behind a proxy.** The rate limiter and the OIDC
  callback throttle keyed on `request.client.host`. Behind the shipped
  same-origin nginx profile every caller shares the proxy's address: one abusive
  client rate-limits everyone (self-DoS), and the callback throttle locks out
  every user at once. There was no trust model for `X-Forwarded-For` — and
  honouring it unconditionally would let any caller spoof its identity.
- **Unvalidated inbound `X-Request-ID`.** An arbitrary attacker-supplied header
  value flowed verbatim into every structured log line and back out as a
  response header — a log-injection vector.

## Decision

### 1. Timing-equalized `authenticate`

`terp-cap-auth` gains `verify_password_dummy()`: one Argon2 verification against
a lazily built fixed dummy hash (never at import time), result discarded. Every
pre-verify refusal path in `IdentityService.authenticate` — unknown email,
inactive account, SSO-only user with no local credential — burns it, so a
refusal is timing-indistinguishable from a wrong password.

### 2. A declared proxy trust model, one resolved caller identity

`SecurityConfig` gains `trusted_proxy_hops` (default `0`): how many reverse-proxy
hops in front of the app are trusted to append `X-Forwarded-For` entries. The
central stack installs a `ClientIpMiddleware` that resolves the caller once:

- `0` hops (default): forwarding headers are attacker-supplied and **ignored**;
  the direct TCP peer identifies the caller — the historical behaviour.
- `h > 0` hops: the `h`-th `X-Forwarded-For` entry from the right (the address
  the outermost trusted proxy saw) identifies the caller. Anything left of it is
  client-supplied and never trusted. A missing header, too few entries, or a
  non-IP value falls back to the direct peer — toward the stricter key, never
  toward an attacker-chosen one.

The resolved address lands on `request.state.client_ip` and is read through one
public helper, `terp.core.client_ip(request)` — the single sanctioned way to
identify a caller by network address. The rate-limit key and the OIDC callback
throttle key both use it; a module must never parse `X-Forwarded-For` itself.

### 3. Request-id validation

`RequestIdMiddleware` honours an inbound id only when it matches a strict shape
(`[A-Za-z0-9._-]{1,128}`); anything else is replaced with a fresh id, never
echoed into logs or headers. Proxy/SDK correlation keeps working — every sane
correlation id fits the shape.

## Consequences

- A deployment behind the shipped proxy profile sets
  `SecurityConfig(trusted_proxy_hops=1)` to throttle real clients; the default
  stays `0` so no existing deployment silently starts trusting a spoofable
  header.
- Refused logins cost one Argon2 verification — negligible against the
  legitimate-login baseline, and exactly the point.
- These are runtime-only controls (no new arch rule): each is a behaviour of the
  central stack itself with no module-authored surface to police, mirroring the
  ADR 0032 precedent. The runtime tests live in the gate
  (`tests/architecture/test_security_middleware.py`,
  `tests/architecture/test_framework_stack.py`,
  `tests/architecture/test_oidc.py`).

Deferred from the same audit (tracked, not silently dropped): sealing webhook
signing secrets at rest, JWT `aud`/`iss` claims + key rotation, DB-level audit
append-only enforcement, and upload magic-byte sniffing — all four closed by
[ADR 0076](0076-webhook-secret-sealing-jwt-rotation-audit-append-only-and-upload-sniffing.md).
