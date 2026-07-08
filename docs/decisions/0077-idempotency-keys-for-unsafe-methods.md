# 0077 — Idempotency keys for unsafe methods

- **Status:** Accepted
- **Date:** 2026-07-06
- **Relates:** [ADR 0036](0036-distributed-throttle-store.md) (the pluggable-store
  quadruple this seam mirrors, beside the cache store),
  [ADR 0006](0006-cross-cutting-controls-and-opinionation-policy.md) (the
  opinionation policy the shape follows),
  [ADR 0043](0043-jobs-seam-and-typed-enqueue.md) /
  [ADR 0045](0045-durable-outbox.md) (the at-least-once + idempotency contract the
  async side already documents), and
  [ADR 0067](0067-per-module-request-size-allowances.md) (the request-size cap the
  middleware sits inside).

---

## Context

The 2026-06-24 direction & completeness review listed **idempotency keys for
unsafe methods** ("safe client retries at scale") as the last unchecked
production-readiness gap. Without it, a client whose POST times out faces the
classic dilemma: retry and risk a duplicate mutation (a double-created order, a
double-fired webhook subscription), or give up and risk having done nothing. The
platform's async side already commits to *at-least-once + idempotency* (ADRs
0043/0045); the HTTP boundary had no equivalent.

The industry-standard answer (Stripe, the IETF `Idempotency-Key` draft) is a
client-supplied key on the unsafe request: the first execution's response is
stored, and a retry of the same key gets that stored response **replayed** instead
of a second execution.

## Decision

Ship the control as a kernel middleware plus a pluggable store seam — the proven
ADR 0006 quadruple, shaped exactly like the throttle store (ADR 0036) and the
cache store beside it.

**The port (`terp.core.idempotency`).** `IdempotencyStore` — `begin(key,
fingerprint, ttl_seconds)` (an **atomic** claim returning
`started | in_flight | replay | mismatch`), `complete(key, lease, response,
ttl_seconds)`, and `release(key, lease)`. `begin` hands the winning claimant a
**lease**; `complete`/`release` are lease-guarded so a slow finisher whose claim
expired mid-flight can never clobber a newer execution. The default
`InMemoryIdempotencyStore` is per-process and zero-dependency, TTL-expired on
access with the same interval-gated sweep as the in-memory cache store, and
**bounded** (`max_entries`, default 10 000): on overflow the soonest-to-expire
entry is evicted, which only weakens that key back to at-least-once (a retry
re-executes) — never to a wrong response.

**The middleware (`IdempotencyMiddleware`).** Installed by `create_app`
**innermost** in the security stack — inside the request-size cap (so buffering
the body for fingerprinting is bounded, and independently capped at 1 MiB with a
typed 413 beyond it) and inside the per-request headers (so a replay gets a fresh
request id / rate-limit counters / security headers). A request without the
`Idempotency-Key` header is untouched — the control is inert until a client opts
in. With the header, on an unsafe method (POST / PUT / PATCH / DELETE):

- The store key is scoped to the presented `Authorization` credential (hashed,
  never stored raw) — one caller can never replay or probe another's responses.
- The request **fingerprint** (method + path + body digest) rides the entry; a
  key reused for a different request is a typed **422** (`idempotency_key_mismatch`),
  never an answer to a request that was never made.
- A concurrent duplicate (the key still executing) is a typed **409**
  (`idempotency_in_flight`, with `Retry-After`) — never a second execution.
- A malformed key is a typed **400**; only completed non-5xx responses within a
  size cap are stored — a crash, a 5xx, or an over-large response **releases** the
  key so the retry re-executes (at-least-once, matching the jobs contract).
- The store failing on the claim is **fail closed** (typed **503**): without the
  dedup guarantee the mutation is refused, never silently double-executable.
- A replayed response carries `Idempotency-Replayed: true`.

**The boot guard.** `create_app(idempotency_store=…,
require_shared_idempotency_store=…)`: a multi-instance deployment wires one shared
backend (marked via `mark_shared_idempotency_store`) so a retry landing on another
worker still replays; with the promise declared, boot refuses an unmarked
per-instance store (`BootError`) — mirroring the shared-throttle-store and
shared-cache-store guards. Default `False`: the per-instance default is unchanged
and correct for a single process.

Per ADR 0006 this is runtime + boot + kernel-test only — **no `terp.arch` AST
rule** applies, because there is no module-authored pattern to police (a module
never sees the middleware or the store; the control lives entirely in the
composition path).

## Consequences

- A client can retry any unsafe request safely by attaching an `Idempotency-Key`;
  nothing changes for clients that don't.
- The dedup scope is the presented credential: a token refresh mid-retry starts a
  fresh scope (the retry re-executes). This is the conservative failure direction
  and matches per-API-key scoping elsewhere; principal-level scoping would need
  auth in the middleware and is deliberately out of scope.
- Bodies over the 1 MiB fingerprint cap (e.g. `files` uploads under their ADR 0067
  allowance) cannot use the header — refused with a typed 413, never silently
  buffered unbounded or half-honored. Uploads already dedupe naturally on the
  files capability's SHA-256-derived storage.
- A shared (e.g. Redis-backed) `IdempotencyStore` adapter is follow-up work, like
  the throttle- and cache-store backends; the port is deliberately engine-free.
