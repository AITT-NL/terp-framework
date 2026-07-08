# 0024 - Built-in health endpoints + connection-pool configuration

- **Status:** Accepted
- **Date:** 2026-06-25
- **Context phase:** Phase 2 (base profile) — production-readiness
- **Relates:** [ADR 0015](0015-runtime-write-guarded-session.md) (the write-guarded
  `SessionDep` the readiness ping reads through), the production-readiness gaps in
  the [direction & completeness review](../internal/reviews/2026-06-24-direction-and-completeness-review.md).

---

## Context

A deployable platform needs two things Terp lacked: health/readiness endpoints for
orchestrators (Kubernetes) and load balancers to probe, and connection-pool tuning
for the database under load. The engine factory called `create_engine` with
defaults (no pool sizing, no pre-ping, no recycle), and there was no health route —
so a load balancer could not tell a *ready* instance from a *starting / broken*
one, and a real deployment could not size its pool.

## Decision

1. **Built-in health endpoints, mounted by `create_app` at `/health` (public).**
   - `GET /health/live` — *liveness*: 200 while the process serves; **no** dependency
     check, so a transient database blip never restarts an otherwise-healthy pod.
   - `GET /health/ready` — *readiness*: a `SELECT 1` through the same `SessionDep`
     seam the app uses; `200 {"status":"ready","checks":{"database":"ok"}}` when the
     database answers, `503 not_ready` otherwise, so a load balancer withholds
     traffic until the dependency recovers. The ping is a `Select` — a read the
     write-guarded session permits (ADR 0015) — and goes through `SessionDep`, so it
     honors the configured engine and is overridable in tests.

   They are mounted directly by `create_app` (kernel infra, not a `ModuleSpec`),
   **outside** the policy guard — a probe carries no token. (They still pass
   through the middleware stack, so they inherit rate limits and CORS, but are
   unauthenticated.) Failures in the readiness check are explicitly logged so
   operators have a clear signal when a load-balancer drain occurs.

2. **Connection-pool configuration on `Settings`, applied by the engine factory.**
   `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` / `DB_POOL_TIMEOUT` / `DB_POOL_RECYCLE` /
   `DB_POOL_PRE_PING` (production defaults `5 / 10 / 30s / 1800s / on`, guarded
   by Pydantic `Field` bounds to fail-fast on malformed deployment config). The
   private `_engine_options` applies them **only to a server database** (Postgres
   / MySQL / …); **SQLite** (dev / test, often in-memory) keeps SQLAlchemy's default
   pool, because `pool_size` / `max_overflow` do not apply to it and recycling an
   in-memory connection would discard the database.

## Consequences

- k8s / load-balancer probes work out of the box: liveness restarts a hung process,
  readiness drains a database-disconnected instance.
- A real deployment sizes its pool via env (`DB_POOL_*`) with no code change; dev /
  test on SQLite is byte-for-byte unchanged (`{"echo": False}`).
- The readiness ping reuses `SessionDep`, so it stays consistent with the app's data
  path and is trivially overridable in tests.

## Alternatives considered / deferred

- **A bare `GET /health`** (ambiguous live-vs-ready) — rejected for explicit
  `/health/live` and `/health/ready`.
- **Statement timeout** — *deferred*: it is database-specific (e.g. Postgres
  `connect_args={"options": "-c statement_timeout=..."}`) and best set per
  deployment; the pool knobs cover the common need first.
- **Exempting `/health` from the rate limiter** — *deferred*: at default limits
  probe frequency is well under the cap; a path-scoped exemption is a later tweak.
- **A configurable health prefix / opt-out** — *deferred*: `/health` is conventional
  and always-on is simplest; add a knob only if an app needs it.
