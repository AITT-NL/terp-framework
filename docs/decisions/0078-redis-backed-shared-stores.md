# 0078 — Redis-backed shared stores for idempotency, throttling, and cache

- **Status:** Accepted
- **Date:** 2026-07-07
- **Relates:** [ADR 0036](0036-distributed-throttle-store.md) (the shared
  throttle-store seam), [ADR 0077](0077-idempotency-keys-for-unsafe-methods.md)
  (the idempotency store port and explicit Redis-adapter deferral), and
  [ADR 0006](0006-cross-cutting-controls-and-opinionation-policy.md) (the
  registry + safe default + fail-closed runtime + build-time test shape).

---

## Context

The kernel now exposes three intentionally small store ports whose in-memory defaults are
correct for a single process but not globally honest across replicas:

- `IdempotencyStore` protects unsafe HTTP retries by atomically claiming a key, replaying a
  completed response, rejecting fingerprint reuse, and lease-guarding completion/release.
- `ThrottleStore` backs the request rate limiter and login lockout fixed-window counters.
- `CacheStore` is an optional hot-read cache with mandatory TTLs.

ADRs 0036 and 0077 deliberately kept Redis out of `terp.core`: the kernel defines the seam
and the boot guards; engine adapters belong in opt-in capability packages. The missing piece
was one shared backend a production composition root can wire when it declares
`require_shared_*` for a horizontally scaled deployment.

## Decision

Ship `terp-cap-redis`, a library capability with no models, routes, or migrations. It owns
only `terp.capabilities.redis` and provides:

- `RedisIdempotencyStore`, constructed from a redis-py compatible client or URL. `begin`,
  `complete`, and `release` are Lua-scripted transitions so a new claim, mismatch check,
  in-flight check, replay read, and lease-guarded completion/release are indivisible.
  Every Redis hash has an expiry; a stale lease can neither overwrite nor delete a newer
  claim.
- `RedisThrottleStore`, using one TTL string for the fixed-window counter and one TTL
  string for the lock. The counter uses a Lua `INCR` + first-hit `EXPIRE` script so all
  replicas observe one window and one reset time.
- `RedisCacheStore`, a Redis string cache with native `EX` TTLs for `get` / `set` /
  `delete`.
- `RedisStoreBundle`, a convenience constructor for deployments that back all three seams
  with one Redis cluster.

Each adapter marks itself with the public `mark_shared_idempotency_store`,
`mark_shared_throttle_store`, or `mark_shared_cache_store` marker. That keeps the kernel's
boot promises fail-closed without importing any internal core module from the capability.

## Consequences

- Multi-replica deployments can now get global idempotency, throttling, lockout, and cache
  behaviour by wiring the Redis adapters into `create_app` and enabling the existing
  `require_shared_*` guards.
- Single-process defaults are unchanged: Redis remains an optional capability dependency,
  not a kernel dependency.
- The package is migration-less and route-less, so OpenAPI contracts and SQL migration
  conformance do not change.
- Tests use an in-repo Redis double for the narrow command surface, keeping the gate
  hermetic while still exercising the adapter's Lua-script entry points and lease races.
