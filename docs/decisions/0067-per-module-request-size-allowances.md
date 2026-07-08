# ADR 0067 — per-module request-size allowances (`ModuleSpec.max_request_bytes`)

- Status: Accepted
- Date: 2026-07-04
- Phase: Phase 2 hardening (closes ADR 0066's known follow-up)
- Relates to: ADR 0066 (streamed files port — whose review surfaced the effective
  `min(MAX_UPLOAD_BYTES, security.max_request_bytes)` ceiling), ADR 0005 (the security
  middleware stack + `SecurityConfig.max_request_bytes`), ADR 0056/0057 (the files
  capability that consumes the seam), ADR 0006 (two-layer discipline), ADR 0011 (traits
  declare the *which*, the composition root configures the *how*)
- **Edits `terp.core`** (`module_spec.py`, `app.py`, `_internal/middleware.py`) — the
  vendored agent-visibility mirror is synced byte-exact (ADR 0034).

## Context

The kernel's `RequestSizeLimitMiddleware` bounds **every** request body at one global
`SecurityConfig.max_request_bytes` (default 1 MiB). That is the right deny-by-default
posture — but it made the files capability's 25 MiB upload cap unreachable out of the box
(effective ceiling `min(25 MiB, 1 MiB) = 1 MiB`), and the only lever was raising the
*global* cap, widening the DoS surface of every endpoint to accommodate one
body-carrying route. The files cap itself was also a hard-coded constant: a deployment
could not retune it without forking the package.

## Decision

### 1. A module declares its own request-body ceiling

`ModuleSpec` gains `max_request_bytes: int | None = None` (validated positive when set):
the module *declares* the ceiling for its **own** mount prefix, and the kernel enforces
it centrally — the ADR 0011 shape (the manifest declares the *which*; the kernel owns the
*how*). `create_app` derives a prefix→cap map from every **mounted** spec
(`/api/v1/<name>`; a router-less spec is skipped — an unrouted prefix must never accept a
bigger body) and hands it to `RequestSizeLimitMiddleware`, which now resolves the
effective cap per request by **longest matching path prefix** (whole-segment matching, so
`/api/v1/files-evil` never inherits `/api/v1/files`'s allowance); every unmatched path
keeps the global cap. Deny-by-default is preserved: nothing gets a bigger body unless a
mounted module explicitly declared it.

Authorization ordering for body-carrying routes is route-shape dependent: FastAPI parses
body parameters (for example `UploadFile`) before included-router dependencies. A route
that needs the larger allowance must therefore parse the body explicitly **inside** the
handler, after the policy guard dependencies have run. The files upload route follows that
shape (`Request` parameter only, then `request.form(...)` inside the handler), so an
unauthenticated or under-privileged caller is refused before multipart spooling; a
regression test locks this down.

### 2. The composition root retunes per deployment

`create_app(request_size_overrides={"files": 100 * 1024 * 1024})` — keyed by **module
name** (the platform vocabulary), winning over the spec's declared default, and
fail-closed: an unknown / unmounted name or a non-positive cap raises `BootError` at
composition time, so a typo cannot silently create (or fail to create) an allowance.

### 3. The files capability consumes the seam

- The files `ModuleSpec` declares `max_request_bytes = MAX_UPLOAD_BYTES + 64 KiB` — the
  stored-bytes cap plus multipart framing headroom, so a maximum-size upload fits through
  the middleware without widening the global cap. The out-of-the-box 25 MiB upload now
  actually works (closing ADR 0066's follow-up).
- The stored-bytes cap becomes composition-root-configurable:
  `configure_upload_limit(max_bytes)` / `active_upload_limit()` / `reset_upload_limit()`
  (the same seam shape as the storage registry; validated eagerly). A deployment raising
  it beyond the declared allowance pairs it with the matching `request_size_overrides`
  entry — two explicit, greppable composition-root lines; forgetting the second line
  fails closed (the middleware still refuses the larger body first).

## Two-layer enforcement (ADR 0006)

Runtime: the middleware's per-prefix cap (fail-closed to the global cap), the `BootError`s
on invalid overrides, and the eager `ValueError`s on invalid declarations/limits.
Build-time: middleware prefix-matching tests (including the lookalike-sibling case),
`create_app` wiring tests (declared allowance honored, explicit override precedence,
unknown-name and non-positive refusals, router-less exclusion), and the example-app
end-to-end proof — a 1.5 MiB upload (over the global 1 MiB cap) round-trips through
`/api/v1/files` while the same body on `/api/v1/notes` stays 413. No new AST rule: the
seam introduces no module-authored pattern to police (declaring `max_request_bytes` on a
spec is exactly as reviewable as declaring a `Policy`).

## Consequences

- The OpenAPI contract is unchanged (the allowance is transport-level, not schema-level).
- `terp.core` changed → the vendored mirror (`vendor/terp-core`) is re-synced byte-exact;
  the `test_vendored_core_unmodified` gate holds.
- A declared allowance covers traffic before routing only at the byte-counting middleware
  layer. Body-carrying handlers on an allowance-holding prefix must avoid FastAPI body
  parameters and parse inside the already-guarded handler; otherwise multipart parsing can
  run before authentication. The files route uses the guarded `Request` pattern and the
  example test verifies anonymous malformed multipart returns `401`, not a parser `400`.
- The `terp guide files` recipe documents the two-line deployment retune.
- Deferred: surfacing declared allowances in `terp inspect`, and a per-tenant or
  per-principal allowance (would need the principal, which the middleware deliberately
  does not resolve).
