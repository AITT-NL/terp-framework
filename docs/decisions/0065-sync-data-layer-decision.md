# 0065 - The data layer stays sync (a documented decision)

- **Status:** Accepted
- **Date:** 2026-07-04
- **Context phase:** Production-readiness gaps (the 2026-06-24 direction &
  completeness review — "Decision required and to be documented")
- **Relates:** [ADR 0024](0024-health-endpoints-and-pool-config.md) (the pool tuning
  this decision leans on), [ADR 0064](0064-keyset-cursor-pagination.md) (the other
  data-layer scale decision), [ADR 0015](0015-runtime-write-guarded-session.md) /
  [ADR 0038](0038-base-service-commit-ownership.md) (the session machinery that would
  have to be duplicated for async)

---

## Context

FastAPI is async, but Terp's data layer is **sync**: one SQLModel `Session` per
request, executed in Starlette's threadpool (a sync `def` route never blocks the
event loop — Starlette dispatches it to a worker thread). The direction &
completeness review called this out as the one concurrency choice that must become a
**conscious, documented decision**: stay sync (simpler, fine for the majority, with
explicit limits + pool tuning) or offer an async-session path. "Either is
defensible; silence is not."

## Decision

**Terp stays sync, deliberately.** The rationale, in order of weight:

1. **The security spine is session-shaped.** The write-guarded session (ADR 0015),
   the re-entrant commit-owning chokepoint (ADR 0038), the runtime row-scope
   backstop (`apply_row_scope` on `exec`/`scalars`/`scalar`/`get`), and the audit
   emit all wrap the sync `Session`. An async path would mean maintaining a **second,
   parallel implementation of every fail-closed control** — the highest-risk kind of
   duplication this platform exists to prevent. One enforced path beats two
   half-enforced ones.
2. **The ceiling is real but high, and it is tunable.** Throughput is bounded by the
   threadpool size × the connection pool, both explicit knobs: `DB_POOL_SIZE` /
   `DB_MAX_OVERFLOW` / `DB_POOL_TIMEOUT` / `DB_POOL_RECYCLE` / `DB_POOL_PRE_PING`
   (ADR 0024) govern the engine, and horizontal scaling adds workers (the shared
   `ThrottleStore`, ADR 0036, already keeps the cross-instance controls correct).
   The per-request work Terp encourages is short, indexed CRUD — exactly the shape
   the threadpool model serves well; ADR 0064 removes the one systemic query-cost
   trap (deep offset + mandatory count).
3. **Slow work has a first-class home off the request path.** Anything that would
   actually hold a thread — external calls, exports, fan-out — belongs on the jobs
   seam (ADR 0043) / durable outbox (ADR 0045) / webhooks (ADR 0051), not in a
   route. The platform's own long-I/O capabilities already comply.
4. **A module author cannot get it wrong.** Routes are sync `def` by convention and
   scaffold; there is no async session to misuse on the hot path. (An async route
   that does its own non-DB awaiting remains legal FastAPI — the guard rails concern
   the data layer.)

**Revisit trigger:** a real deployment demonstrating threadpool saturation that pool
tuning + workers + the jobs seam cannot absorb. If that occurs, the path is an async
engine behind the same `SessionDep` seam with the full control set ported — never an
unguarded `AsyncSession` side door.

## Consequences

- The review's open question is closed: sync is the documented, load-bearing choice,
  not an accident. `AGENTIC_PLATFORM_DESIGN` / the deployment guide can point here.
- The decision is enforced socially + by scaffolding (no async-session export from
  `terp.core`), not by a new arch rule — there is no module-authored pattern to
  police (the honest two-layer shape per ADR 0006: no spurious rule).
- The known limit stays visible: a single very slow sync route can exhaust threadpool
  workers. The mitigation is the jobs seam, documented in the guide and this ADR.
