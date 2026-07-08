# Direction & Completeness Review — Terp backend framework

**Date:** 2026-06-24
**Reviewer role:** staff engineer / platform architect
**Question asked:** Is Terp on track to let **non-technical users and agentic coders**
build a backend *without worrying about security* (given a well-defined control
plane)? Is it **flexible for all use cases**? Does it cover what a **complex, large
web application** needs, and is it **implemented well** (performance, concurrency)?

> Companion to the [adversarial design review](2026-06-24-adversarial-design-review.md)
> (which red-teamed the *security* thesis). This review is about **direction,
> completeness, and production-readiness**. Newly-surfaced gaps (marked ★ below) are
> folded into [docs/STATUS.md](../STATUS.md) so nothing is lost.

---

## 1. Verdict

**The direction is right and the security/correctness spine is genuinely strong and
differentiated.** Today Terp is an excellent *secure-by-construction substrate*
(kernel + opt-in capabilities + two-layer enforcement + a typed control plane). It
is **not yet a complete backend platform** for a large app: several
production-critical subsystems (schema migrations, health/readiness probes,
background jobs, observability, object-level authorization) are unbuilt, and a few
concurrency/performance choices (sync DB, no pool tuning, exact `COUNT`, per-instance
rate limiting, no caching) need to become **conscious, documented decisions**. None
are design dead-ends — they are scope not yet reached (we are at Phase 2 of 9).

The headline "a non-technical user / agent cannot ship the common insecure patterns"
is **largely true for the slice built**, and was just hardened materially (ADR 0014
capability arch-scan + chokepoint, ADR 0015 runtime write-guard, ADR 0016 real
permission enforcement). The **biggest near-term risk to the thesis is ergonomic, not
security**: the router is still hand-typed per module (a drift surface), and there is
no scaffolding / CLI / cookbook yet — exactly the authoring affordances the target
audience needs.

## 2. Genuinely strong (keep doing this)

- **Two-layer enforcement** (a fail-closed runtime control *and* a build-time arch
  rule) with the escape-hatch **budget ratchet** and the **capability arch-scan** —
  the framework now dogfoods its own rules.
- **Deny-by-default authorization** + **fail-closed composition**: `create_app`
  `BootError`s on a missing policy, a missing durable audit sink in production, a
  duplicate capability name, a discovery failure, and now a permission policy with no
  enforcer.
- **Audited write chokepoint** + the **runtime write-guarded session** (ADR 0015) —
  persistence outside `BaseService` fails closed regardless of variable name.
- **Auto-honored model traits** (soft-delete, actor-stamping, OCC `version`) — the
  module writes zero cross-cutting code and an arch rule forbids hand-rolling them.
- **Typed control plane + permission model**, with permissions now enforced as **real
  per-subject grants** (ADR 0016), not silently degraded to a rank.
- **Clean, uniform module shape** (`models` / `schemas` / `service` / `router` /
  `ModuleSpec`); capabilities are independently-installable packages.

## 3. Authoring experience (the target audience)

**Strong:** a module is ~5 small files; cross-cutting concerns are automatic; an
agent now *cannot* bypass the audit trail, drop the tenant/soft-delete predicate via
a managed column, evade the write guard by renaming a session, or ship a `Permission`
that is silently just a rank.

**Friction / gaps (highest leverage first):**

1. **No `build_crud_router` yet (Tier-C sugar).** Every module re-types five CRUD
   endpoints plus `Page.of([Read.model_validate(r) for r in rows], …)`. This is the
   **#1 drift and error surface** for non-technical users and agents, and the single
   highest-leverage ergonomic win. *(On the backlog; should be prioritized — it is the
   authoring centerpiece.)*
2. **Response-DTO drift (H3, open).** `response_model` may be a `table=True` model
   (over-exposure), and forgetting `Read.model_validate(...)` yields ORM-in/ORM-out.
   `build_crud_router` + the H3 rule together close this class.
3. **No scaffolding / CLI / template / cookbook.** `terp new module`, a copier
   template, and per-concern agent recipes are the difference between "an expert can
   apply the patterns" and "a non-technical user / agent can *generate* correct
   modules." *(Phase 5, unbuilt.)*
4. **No object-level authorization pattern.** "May this caller edit *this* row
   (ownership)?" is hand-rolled in the service today (and risks dropping the scope
   predicate, H2). A first-class ownership / row-policy seam would keep agents safe
   for the most common real-world authorization need. ★

## 4. Feature completeness for a complex, large web app

Categorized gaps; **severity = impact on a real large app**. Many are already
tracked; **★ = newly surfaced here and added to the backlog.**

| Area | Capability | Status | Severity |
|---|---|---|---|
| Schema evolution | Packaged Alembic migrations | deferred (Phase 7) | **Critical** — cannot evolve a production schema safely |
| Ops | Health / readiness / liveness endpoints | ★ absent | **High** — every real deployment needs them |
| Async work | Background jobs / scheduler / retries | ★ absent | High |
| Events | Durable transactional outbox (at-least-once, multi-instance) | deferred (ADR 0008) | High — in-proc events are lost across instances / on crash |
| Data | Keyset / cursor pagination + optional total | M5 | High at scale |
| Perf | Engine / connection-pool config (size, overflow, `pool_pre_ping`, recycle, timeout) | ★ absent | High |
| AuthN | Refresh-token rotation + revocation / deny-list | M4 | High |
| AuthN | Login lockout / brute-force throttle | L3 | High |
| AuthZ | Object-level / ownership / row policy seam | ★ absent | High |
| Multi-tenant | First-class wiring + tenant-aware login | H7 / H8 | High (for SaaS) |
| Observability | OpenTelemetry traces + metrics | deferred | High at scale |
| Perf | Caching seam (e.g. Redis) | ★ absent | Medium |
| Ops | Idempotency keys for unsafe methods | ★ absent | Medium |
| Integration | Outbound webhooks / notifications | ★ absent | Medium |
| Storage | Files / object storage (`terp-cap-files`) | backlog | Medium |
| Realtime | WebSockets / SSE (Phase E) | deferred | Medium |
| Secrets | Sealing (encrypt / mask / decrypt) | backlog | Medium |
| AuthN | SSO / OIDC / SAML, API keys / service accounts | backlog | Medium |
| Concurrency | Distributed rate limit + shared admin lock | L3 | Medium (single-instance OK today) |
| Frontend | Contract + Stack A/B | Phase 4+ | per roadmap |

## 5. Performance & concurrency (honest assessment)

- **Sync SQLAlchemy in a threadpool.** FastAPI is async but the data layer is sync
  (one `Session` per request, executed in Starlette's threadpool). This scales
  acceptably for most apps but has a real ceiling (threadpool size) and blocks the
  event loop if a sync route does slow I/O. **Decision required and to be documented:**
  remain sync (simpler; fine for the majority) with explicit limits + pool tuning, or
  offer an async-session path. Either is defensible; silence is not.
- **No engine/pool configuration.** `create_engine(url, echo=False)` uses defaults —
  no `pool_size` / `max_overflow` / `pool_pre_ping` / `pool_recycle` / statement
  timeout. A large app needs these (and `pool_pre_ping` to survive dropped
  connections). ★ Add to `Settings` + the engine factory.
- **Exact `COUNT(*)` on every list (M5).** Dominates cost on large tables; offer
  keyset pagination and an opt-out of the total.
- **Per-instance rate limit + per-process admin `RLock`.** Neither serializes across
  instances, so horizontal scaling dilutes the rate limit and the last-admin guard.
  Correct multi-instance behavior needs a shared store. *(Single-instance is correct
  today; documented as a known limit.)*
- **No caching layer.** Every read hits the database.
- The ADR-0015 write guard adds one `ContextVar` read per write — negligible.

## 6. Security model completeness

A strong base (deny-by-default authz, unbypassable audit, runtime write-guard, real
permission grants). Still open, in priority order: **H2** (make the `base_query` scope
predicate non-overridable — the last structural cross-tenant/soft-delete hole),
**H3** (forbid a `table=True` `response_model`), object-level authorization (★),
refresh-token rotation/revocation (M4), login lockout (L3), over-posting rule (M6),
input-cap breadth (M2), CSRF-if-cookie documentation (M7), and first-class tenancy
(H7/H8). All are tracked; **H2 and H3 are the next two structural items.**

## 7. Recommended re-prioritization

To move from "secure substrate" toward "a non-technical user / agent can build a real
app," the suggested sequence:

1. **H2 + H3** — close the last two structural authorization / over-exposure holes
   (cheap, high-value, two-layer).
2. **`build_crud_router` (Tier-C) + response-DTO discipline** — the authoring
   centerpiece for the target audience (kills router drift and the H3 class together).
3. **Health/readiness endpoints + engine/pool config** — small, unblock real deploys.
4. **Packaged Alembic migrations** — the critical production gap.
5. **Object-level authorization seam** (ownership / row policy).
6. **H7/H8 first-class multi-tenant + tenant-aware login.**
7. **Background jobs + durable outbox**, then **observability (OTel)**, **caching**,
   and **refresh rotation / login lockout**.
8. Scaffolding (`terp new module`) + per-concern **agent cookbook** (Phase 5) — the
   force-multiplier for the non-technical / agent audience, layered on the above.

## 8. Documentation status

[docs/STATUS.md](../STATUS.md) and [docs/IMPLEMENTATION_PLAN.md](../IMPLEMENTATION_PLAN.md)
are current for what is built. This review adds the production-readiness gap analysis;
the ★ items are now recorded in the STATUS backlog under
**“Production-readiness gaps (2026-06-24 review)”** so the roadmap stays complete and
nothing is lost between sessions.
