# 0005 - Security middleware and structured logging (SecurityConfig)

- **Status:** Accepted
- **Date:** 2026-06-24
- **Context phase:** Phase C (core security middleware + structured logging)
- **Supersedes/relates:** [docs/IMPLEMENTATION_PLAN.md](../internal/IMPLEMENTATION_PLAN.md) §5 Phase C,
  [ADR 0002](0002-control-plane-and-auditable-module-authority.md) §3.2 (SecurityConfig registry),
  [ADR 0003](0003-conformance-and-coverage-gate.md)

---

## Decision

Terp adds a central **`SecurityConfig`** registry to the control plane and the
middleware + logging that enforce it, so every HTTP cross-cutting security
control is declared **once** per application and installed by `create_app` — a
module can neither define a divergent posture nor hand-roll its own.

`terp.core.SecurityConfig` aggregates four typed declarations:

1. **`SecurityHeaders`** — `X-Content-Type-Options`, `X-Frame-Options`,
   `Referrer-Policy`, `Permissions-Policy`, `Content-Security-Policy`, and `HSTS`
   (applied only outside local development).
2. **`CorsPolicy`** — **deny-by-default**. The default denies all cross-origin
   access *and* is marked unconfigured, so a production boot **refuses** until the
   app makes an explicit choice: `CorsPolicy.allow([...])` (an allowlist; `"*"` +
   credentials is a construction error) or `CorsPolicy.disabled(reason=...)` (a
   conscious, greppable opt-out).
3. **`RateLimit`** — a per-process fixed-window request cap (enabled by default;
   `RateLimit.disabled()` is an explicit opt-out rejected in production).
4. **`max_request_bytes`** and **`request_id_header`** — a body-size cap and the
   correlation-id header name.

`create_app` installs the middleware stack from this single declaration
(outer→inner: CORS · request-id · security-headers · rate-limit ·
request-size-limit) and calls `configure_logging()` once. Structured logging
ships a `request_id` context var (set per request by the request-id middleware),
a `RedactingFilter` that scrubs `Authorization`/`Bearer`/secret-like values out
of every log record, and a JSON `StructuredFormatter`.

**Production fail-fast is extended**: under `ENVIRONMENT == "production"`,
`create_app` raises `BootError` when the security config is unsafe (CORS unset,
CORS `"*"`, or rate-limiting disabled). This complements the existing
`Settings` guardrails (weak secret / DEBUG / SQLite / `"*"` CORS).

## Two-layer enforcement

Per the platform invariant, every control is a fail-closed **runtime** control
*and* a build-time **`terp-arch`** rule (added to `_ALL_RULES`, each with a
matching `test_<rule>` enforced by the harness self-completeness meta-test):

| Control | 🔒 Runtime (fail-closed) | 🧪 Build-time (terp-arch) |
|---|---|---|
| Security headers / CORS / rate-limit / body-size / request-id are centralized | `create_app` installs the stack from the one `SecurityConfig`; a module only ever holds an `APIRouter`, never the app | `no_adhoc_middleware` — bans `add_middleware(...)` and `BaseHTTPMiddleware` subclasses in app modules |
| Structured logging + PII redaction is centralized | `configure_logging()` installs the redaction filter on the root logger at boot | `no_adhoc_logging_config` — bans `logging.basicConfig` / `dictConfig` / `fileConfig` in app modules |
| Production runs only on a safe security posture | `create_app` raises `BootError` on unsafe CORS / disabled limits in production | extends the `config` production guardrails (runtime) backed by the kernel-coverage tests |

> **Rule-name note.** The implementation plan §6 sketched
> `security_config_present` / `prod_guardrails`. Those describe intent; the
> *enforceable* build-time rules in the current app-scanning model are the two
> **centralization** rules above (the same family as `no_app_instantiation` /
> `no_raw_session_construction`). The "security config present / production-safe"
> guarantee is enforced at **runtime** (the `SecurityConfig` registry is a
> required, defaulted field of `ControlPlane`, and `production_problems()` fails
> the boot), with dedicated runtime tests — never a build-time-only control.

## Rationale

The target user is non-technical and works through agents, so "remember to set
security headers" or "don't forget CORS" cannot be the control. Making the
posture a single typed declaration that the framework installs means:

- two modules can never ship divergent security (no drift);
- a forgotten control is **off safely** (deny-by-default), and the one control
  that cannot be defaulted safely — which origins to trust — **fails the
  production boot** until declared;
- a careless `log.info(f"... {token}")` cannot leak a credential, because
  redaction is installed centrally and a module cannot reconfigure logging.

This keeps the audit surface small: the security posture is one object in the
control plane, reviewed once, not scattered through routers.

## Consequences

- `terp.core` grows a public `SecurityConfig` / `CorsPolicy` / `SecurityHeaders`
  / `RateLimit` surface and a `configure_logging` / `request_id_ctx` /
  `get_request_id` logging surface. The middleware implementations live under
  `terp.core._internal` (a module cannot import or attach them).
- `ControlPlane` gains a `security: SecurityConfig` field (defaulted, so existing
  apps boot unchanged); `create_app` validates it in production and installs the
  stack.
- `terp-arch` grows two centralization rules (`no_adhoc_middleware`,
  `no_adhoc_logging_config`); the example app dogfoods them clean and the
  escape-hatch budget stays `{}`.
- The example app declares a top-level `control_plane/security.py`
  (`CorsPolicy.disabled(reason=...)` — it is exercised server-to-server in tests).
- The error envelope now sources its `request_id` from the request-id middleware,
  so the body and the `X-Request-ID` response header agree. The envelope shape
  `{code, detail, request_id}` is unchanged.
- Rate-limit state is per-app-instance (a fresh build resets it); distributed
  limiting (a shared store) is a later, opt-in concern.

## Implementation checkpoints

Phase C is complete only when all of these are true (all met):

- `SecurityConfig` declares headers, CORS (deny-by-default), rate-limit,
  body-size, and request-id, and `create_app` installs the matching middleware.
- A production boot refuses on permissive/unset CORS or a disabled rate limit.
- Logging redacts secrets and carries a `request_id` context var.
- `no_adhoc_middleware` and `no_adhoc_logging_config` are registered, tested, and
  pass clean on the example app (budget `{}`).
- The full gate is green at **100% line coverage** (179 tests).

Status: **Accepted** — 179 tests green, 100% line coverage; the security
middleware + structured-logging substrate is centralized in the control plane.
