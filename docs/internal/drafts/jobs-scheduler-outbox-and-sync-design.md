# Jobs · Scheduling · Durable Delivery · Sync — working design (DRAFT / temporary)

> **Status: DRAFT — not an ADR.** A scratch design to align on shape before any code.
> When accepted, split into ADRs (next free number is **0043**): e.g. `0043 jobs seam`,
> `0044 durable outbox`, `0045 scheduler seam`, `0046 sync capability`. Delete or fold this
> file into those ADRs once they land. Calibrate against the source of truth:
> [AGENTIC_PLATFORM_DESIGN.md](../../../AGENTIC_PLATFORM_DESIGN.md),
> [IMPLEMENTATION_PLAN §10](../IMPLEMENTATION_PLAN.md), [STATUS](../STATUS.md), and the
> precedent ADRs cited inline.

---

## 0. TL;DR

Build **ports first, engines as adapters, sync last**. `terp.core` defines tiny, typed,
serializable **job / schedule** ports with safe in-process defaults — exactly the shape
already proven by `EventDispatcher` (ADR 0008), `ThrottleStore` (ADR 0036), and `AuditSink`
(ADR 0007). Concrete engines (Celery, Redis, Azure Service Bus, multiprocessing, Temporal)
are **opt-in capability packages** the consumer wires at `create_app(...)`. The durable
outbox is the reliable post-commit delivery mechanism, added as a drop-in dispatcher. "Sync
between two systems" is a **consumer capability** (`terp-cap-sync`) written only against the
ports — never against an engine — so users keep all options without rewriting domain code.

Build order: **jobs → outbox → adapters → sync.**

---

## 1. Goals & non-goals

**Goals**
- Stay abstract: `terp.core` imports **no** engine (no `celery` / `redis` / `azure-*` /
  `apscheduler` / `multiprocessing` in core). Enforced, not aspirational — the existing
  `import-linter` layer-0 contract + `test_core_boundary` fail the build on an upward import.
- Offer every option: in-process, multiprocessing, worker containers, Celery, RQ, Dramatiq,
  Azure Service Bus, Redis Streams/Kafka, Temporal — all selectable at composition time.
- Secure / correct by default (ADR 0006 Tier A/B/C): a safe in-process default runs with zero
  infra; production reliability is opt-in and boot-guarded.
- Reuse the existing machinery: the audited `BaseService` chokepoint, the audit trail, the
  scope/actor/owner registries, migrations, the control plane.

**Non-goals**
- A bespoke workflow/orchestration engine. Long-running, replay-deterministic workflows
  (Temporal-shaped) are **too semantically different** to hide behind a queue API — they get a
  separate `WorkflowEngine` port/adapter, not a forced fit into `JobQueue`.
- A low-code DSL for jobs. Jobs are typed Python functions registered in a catalog (mirrors
  the event catalog), never code-genned (ADR 0009 Level-2 stance).

---

## 2. Principle: ports first, engines as adapters, sync as a consumer

The trap is shipping "a sync engine" or "a background engine." That conflates four concerns
that must swap **independently** and buries an engine choice inside domain code. Instead:

- **Mechanism** (run work / schedule / deliver) = abstract ports in `terp.core` + adapters.
- **Domain** (the mappings, the reconcile algorithm, which two systems) = a consumer module
  or `terp-cap-sync`, speaking only ports.

This is the same split Terp already enforces everywhere (core seam + capability adapter).

---

## 3. The four orthogonal ports

| Port | Question it answers | Default (ships in core/CLI) | Adapters (opt-in caps) |
|---|---|---|---|
| `JobQueue` | "run this named unit of work, maybe later, maybe retried" | `InProcessJobQueue` (sync / threadpool) | celery · rq · dramatiq · azure-servicebus · redis · multiprocessing |
| `Scheduler` | "trigger this job on a cron / interval" | **external trigger** via `terp jobs run` (any cron / k8s CronJob / Azure timer calls it) | apscheduler (in-proc) · celery-beat |
| `EventDispatcher` / outbox | "reliably publish after the DB commit" | **already exists** — no-op default (ADR 0008) | `terp-cap-outbox` · servicebus · kafka · redis-streams |
| `WorkflowEngine` | "orchestrate a long-running, resumable, multi-step process" | none (optional) | temporal · durable-functions |

A sync may use all four; the framework must **not** collapse them into one API.

---

## 4. Layering map

```
terp.core.jobs                 ← ports only: types, catalog, ABCs, enqueue(); + InProcessJobQueue default
terp.core._internal.job_runtime ← the worker loop / context binding (modules cannot import it — no_internal_imports)
terp-cap-outbox                ← durable DomainJob/Outbox tables + leased retrying worker + durable dispatcher
terp-cap-jobs-celery|-redis|-azure-servicebus|-multiprocessing  ← JobQueue adapters (depend on the heavy lib)
terp-cap-workflows-temporal    ← WorkflowEngine adapter
terp-cap-sync (or app modules) ← SyncMapping/SyncRun/SyncRecordLog + SyncService, built ONLY on the ports
```

Rule: a sync/domain module depends on `terp.core.jobs` (+ `BaseService`), **never** on Celery /
Azure / Redis directly. An adapter is the only place an engine import is allowed.

---

## 5. Core seam: `terp.core.jobs` (illustrative)

```python
# terp.core.jobs  (layer-0; no engine imports)

@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 5
    backoff_seconds: float = 2.0
    backoff_multiplier: float = 2.0          # exponential
    max_backoff_seconds: float = 300.0
    retry_on: tuple[type[Exception], ...] = (Exception,)

@dataclass(frozen=True)
class JobDefinition:                          # the typed, registered contract (no bare strings)
    name: str                                 # dotted token, e.g. "sync.customers.pull"
    payload_schema: type[BaseSchema]          # validated on enqueue AND on execute
    handler: Callable[["JobContext", BaseSchema], None]   # resolved by NAME, never shipped as a closure
    retry: RetryPolicy = RetryPolicy()
    queue: str = "default"                     # routing hint; adapters may map to a real queue/topic
    visibility: JobVisibility = JobVisibility.INTERNAL

@dataclass(frozen=True)
class JobCatalog:                              # mirrors EventCatalog: index by name, reject dupes
    jobs: tuple[JobDefinition, ...] = ()

@dataclass(frozen=True)
class JobEnvelope:                             # what crosses the wire — must be JSON-serializable
    name: str
    payload: Mapping[str, object]
    idempotency_key: str | None
    actor_id: uuid.UUID | None                 # see §7 — carried so the worker can re-bind context
    tenant_id: uuid.UUID | None
    request_id: str | None
    enqueued_at: datetime
    attempt: int = 1

class JobQueue(ABC):
    @abstractmethod
    def enqueue(self, session: Session, envelope: JobEnvelope) -> str: ...   # -> job id

# the chokepoint a module calls (typed, like emit()):
def enqueue(session: Session, *, job: JobDefinition, payload: BaseSchema,
            idempotency_key: str | None = None) -> str: ...
```

Notes:
- `enqueue()` takes the **`session`** on purpose: a durable/outbox adapter writes the outbox
  row in the *same transaction* as the business write (no dual-write). The in-process default
  ignores `session` and runs after commit (or inline in dev).
- `enqueue()` validates `payload` against `job.payload_schema` and rejects an unregistered job
  — the fail-closed runtime half, exactly like `emit()` rejects non-catalog events.
- `JobContext` carries the bound `session`, actor, tenant, request id, attempt, and the
  `JobQueue` itself (so a handler can enqueue follow-up jobs).

---

## 6. Portability rules (the contract that keeps every adapter viable)

These are the constraints that let in-process → Celery → Azure swap with **zero domain change**.
Bake them into the port from day one (most are enforceable, see §12):

1. **Named + catalog-registered.** A job is referenced by a typed `JobDefinition`, never a bare
   string. (You cannot ship a closure to a remote worker — Celery resolves by name; Azure ships
   a message.)
2. **Serializable payload.** `payload_schema` must round-trip JSON (`model_dump(mode="json")`).
   No Python objects, ORM rows, or lambdas in the payload — pass ids, not entities.
3. **Idempotent by key.** Every job carries an optional `idempotency_key`; at-least-once
   delivery is the realistic default (Azure SB / Celery redeliver), so handlers must be safe to
   re-run. The sync mapping table's unique keys provide natural idempotency.
4. **No result-by-default.** Jobs are fire-and-forget side effects; a result/status backend is
   an optional adapter concern, not part of the core port (avoids coupling to Celery's result
   backend). Status/observability lives in your own tables or the adapter.
5. **Handlers are pure-ish.** A handler gets a `JobContext` (session + bound actor/tenant) and a
   validated payload; it must not read ambient request state (there is none in a worker).

---

## 7. Context propagation into workers — the critical integration detail

This is the part that touches existing Terp machinery and is easy to get wrong.

The audited chokepoint stamps `created_by_id` / `modified_by_id` from `audit_actor_ctx`, and
tenant-scoped reads/writes depend on the tenant ContextVar bound by `TenantMiddleware`. **Both
are bound per HTTP request. A background worker has no request.** ADR 0011 already flagged this
("system actor for jobs"). So:

- The `JobEnvelope` **carries** `actor_id`, `tenant_id`, `request_id` captured at enqueue time.
- The worker (`terp.core._internal.job_runtime`) **re-binds** them before invoking the handler —
  the same async-binder pattern `create_app` uses for the audit actor and read-only flags:
  open `bind_audit_actor(envelope.actor_id)` + the tenant context + a request-id context, run
  the handler inside an `allow_session_writes`-style audited unit, commit once.
- A job with no originating user runs as a configured **system actor** (a control-plane default,
  Tier B), so audit/ownership stamping is never silently `None` in production.
- Because the worker binds the actor, **every write a job makes is still audited and
  owner/actor-stamped** with no special-casing — the chokepoint just works.

Without this, a job either writes unaudited rows (breaks the Tier-A guarantee) or leaks across
tenants (breaks isolation). Treat it as a first-class requirement, with a kernel test.

---

## 8. Safe defaults

- **`InProcessJobQueue`** (core): runs the handler synchronously (or on a bounded threadpool)
  *after* the request's commit. Zero infra; dev/test/single-process behave exactly as today.
  Mirrors `InMemoryThrottleStore` / the no-op dispatcher.
- **External scheduler default**: a `terp jobs run <name> --payload <json>` CLI entrypoint. Any
  scheduler (cron, k8s CronJob, systemd timer, Azure Functions timer, Celery beat) invokes it.
  This imposes *nothing* — it's the most abstract possible scheduler.

So a scheduled sync works **today** with only core + an external cron, no broker.

---

## 9. Durable outbox — `terp-cap-outbox`

The reliable post-commit delivery mechanism (deferred from ADR 0008; the dispatcher seam was
designed for exactly this drop-in).

- **Tables** (own migration history, like `terp-cap-audit`): `outbox_message` (id, kind=
  event|job, name, payload JSON, idempotency_key, status, attempts, available_at, locked_by,
  locked_until, created_at, dispatched_at, dead_lettered_at, last_error). Append + status
  updates only.
- **Transactional write.** The durable `EventDispatcher` / `JobQueue.enqueue` writes the outbox
  row on the `session` it already receives — atomic with the business write. **No `emit()` /
  `enqueue()` call-site changes** (ADR 0008's promise).
- **Leased, retrying worker** (`terp jobs worker` / a worker container entrypoint): claims due
  rows with `SELECT ... FOR UPDATE SKIP LOCKED` (a lease via `locked_by`/`locked_until`),
  invokes the handler or publishes to the broker adapter, marks dispatched, retries with backoff
  per `RetryPolicy`, and **dead-letters** after `max_attempts`. At-least-once.
- **Multi-instance safe**: the lease + `SKIP LOCKED` lets N workers drain one outbox. (A
  distributed lock seam — Redis-shaped, like `ThrottleStore` — can guard "only one run of a
  given schedule" if needed.)

---

## 10. Engine adapters (separate opt-in packages)

Each is a thin `JobQueue` (or `EventDispatcher` / `WorkflowEngine`) implementation depending on
the heavy lib; the consumer installs only what they deploy and wires it in one line.

- `terp-cap-jobs-celery` — `enqueue` → `celery_app.send_task(name, kwargs=payload)`; a Celery
  worker resolves the registered task by name and calls the catalog handler.
- `terp-cap-jobs-azure-servicebus` — `enqueue` → send a JSON message to a queue/topic; a worker
  receives, binds context, dispatches; uses SB DLQ + duplicate detection (idempotency_key as
  `MessageId`).
- `terp-cap-jobs-redis` / `-rq` / `-dramatiq` / `-multiprocessing` — analogous.
- `terp-cap-workflows-temporal` — a different port (`WorkflowEngine.start(workflow, args)`);
  handlers become Activities. Not a `JobQueue`.

Wiring (composition root):
```python
create_app(..., job_queue=CeleryJobQueue(celery_app), event_dispatcher=dispatch_via_outbox,
           require_durable_jobs=settings.is_production)
```

---

## 11. Scheduler seam

```python
@dataclass(frozen=True)
class ScheduleDefinition:
    name: str
    job: JobDefinition
    cron: str                 # or interval; catalog-registered, no bare strings
    payload_factory: Callable[[], BaseSchema] = ...   # what to enqueue each tick

class Scheduler(ABC):
    @abstractmethod
    def register(self, schedule: ScheduleDefinition) -> None: ...
```
Default = external trigger (§8). `terp-cap-jobs-apscheduler` runs an in-process scheduler for
single-instance; Celery beat is an adapter for the Celery stack. Schedules are declared on a
`ScheduleCatalog` (control-plane), boot-validated against the `JobCatalog`.

---

## 12. Two-layer enforcement — the ADR-0006 quadruple

Every new control ships as: ① typed registry + safe default · ② fail-closed runtime · ③
build-time test · ④ budgeted escape hatch. New `terp.arch` rules (each paired with a meta-test
and surfaced in `terp guide rules`, per ADR 0030/0037):

- **`jobs_reference_catalog`** — like `events_reference_catalog`: `enqueue(job=…)`, a
  `@task`/handler registration, and `ModuleSpec` job refs must be typed `JobDefinition`s, never
  bare strings or inline `JobDefinition(...)`. Runtime half: `enqueue()` rejects unregistered.
- **`no_adhoc_background_runtime`** — app modules must not import `celery` / `azure.servicebus`
  / `redis` / `apscheduler` / `multiprocessing` / `threading` directly; only adapter capabilities
  may. Budgeted opt-out for the rare justified case. Runtime half: jobs run through the seam.
- **Boot validation** — every declared job/schedule resolves in its catalog (fail closed at
  `create_app`, like Policy/event refs).
- **Production guard** — `create_app(require_durable_jobs=True)` fails closed unless the wired
  `job_queue`/dispatcher is a **marked durable** one (mirrors `is_durable_audit_sink` /
  `require_shared_throttle_store` markers added in ADR 0040). So prod can't silently ship the
  in-process default that loses jobs on restart.
- **No new AST rule where there's no module pattern** — the worker loop, lease, and serializer
  are framework-internal; their second layer is the kernel test + fail-closed runtime (ADR 0036
  precedent).

Vendored core mirror (`vendor/terp-core/`) must include `jobs.py`; `test_vendored_core_unmodified`
stays byte-exact. 100% coverage gate unchanged.

---

## 13. CLI surface

- `terp jobs run <name> --payload <json>` — enqueue/execute one job (the external-scheduler
  trigger).
- `terp jobs worker [--queue …]` — run the outbox/worker loop (the worker-container entrypoint).
- `terp jobs list` / `terp inspect jobs` — show registered jobs, schedules, queues, retry
  policy, and the wired adapter (generated from the live catalogs, like `terp inspect
  control-plane` / `terp guide rules` — cannot drift).

---

## 14. Building sync on top (consumer capability, not core)

`terp-cap-sync` (or app modules) depends only on `terp.core.jobs` + `BaseService`:

- **Tables** (`BaseTable`, audited, migrated):
  - `SyncMapping` — (entity_type, local_id, remote_id, remote_checksum, last_synced_at, status);
    unique on (entity_type, local_id) **and** (entity_type, remote_id) → idempotent upsert.
  - `SyncRun` — (source, started/finished, status, processed/created/updated/failed counts,
    high-watermark cursor, error summary). **Store aggregates here** so the stats UI never pays
    the per-list `COUNT(*)` cost (review M5).
  - `SyncRecordLog` — append-only (like `AuditEvent`): (run_id, entity, action, outcome,
    message). Plan retention; high-volume.
- **`SyncService(BaseService[...])`** — the reconcile algorithm; all writes through the audited
  chokepoint, so every mapping change is also in the audit trail.
- **Jobs**: `SYNC_PULL`/`SYNC_PUSH` `JobDefinition`s whose handlers read source → diff against
  mappings → upsert target → write `SyncRun`/`SyncRecordLog`. External calls to System B live in
  the **handler** (a worker, post-commit), **never** in `_after_write` (avoids the dual-write
  hazard — open-question #1 from the ADR-0040 review).
- **Schedule**: a `ScheduleDefinition` enqueuing `SYNC_PULL` on a cron.
- **Read endpoints** (policy-gated, paginated): list runs, run detail, record logs, mapping
  status — what the stats/logging frontend renders (alongside `GET /api/v1/audit`). The frontend
  consumes the OpenAPI export (ADR 0041) for a typed client.

---

## 15. Phasing / build order

1. **`terp.core.jobs` port + `InProcessJobQueue` default + `JobCatalog` + typed `enqueue()` +
   context binding (§7) + `terp jobs run` CLI + `jobs_reference_catalog` rule.** Unblocks
   scheduled sync today with zero infra. (ADR 0043)
2. **`terp-cap-outbox`** — durable tables + leased worker + durable dispatcher/queue +
   `require_durable_jobs` boot guard + `terp jobs worker`. (ADR 0044)
3. **First real engine adapter** as a separate cap (Celery *or* Azure SB, whichever you deploy
   first) — proves the seam is genuinely engine-agnostic (like a second tenancy consumer proves
   tenancy). (ADR 0045)
4. **`terp-cap-sync`** on top of the ports. (ADR 0046)
5. **Scheduler adapters** (apscheduler / celery-beat) and **`terp-cap-workflows-temporal`** as
   demand appears.

Each step is small, green, and independently shippable.

---

## 16. Testing & the 100% gate

- Kernel tests (`tests/architecture/test_jobs.py`): catalog dup-reject, typed `enqueue` rejects
  unknown/shadow, payload validation, `InProcessJobQueue` runs post-commit, **context binding**
  (a job's writes are audited + actor/tenant-stamped from the envelope, with a system-actor
  fallback), fail-closed on a raising handler, idempotency-key passthrough.
- Arch meta-tests: `test_jobs_reference_catalog`, `test_no_adhoc_background_runtime` (each
  paired in `_ALL_RULES`, surfaced in `terp guide rules`).
- Boot tests: unregistered job/schedule → `BootError`; `require_durable_jobs=True` + in-process
  default → `BootError`; + marked durable adapter → boots.
- Outbox cap: upgrade/downgrade migration conformance; lease + `SKIP LOCKED` concurrency;
  retry/backoff; dead-letter; at-least-once redelivery. Adapters live in their own packages with
  their own suites (not under the core `--cov=terp` gate, like other caps).

---

## 17. Open questions / risks

- **Exactly-once vs at-least-once.** Realistic default is at-least-once + idempotency. Document
  it loudly so handler authors design for re-run. (Azure SB duplicate detection / Celery
  redelivery both push this way.)
- **Result/status backend.** Keep it out of the core port; expose via the adapter or your own
  tables. Revisit only if a real need appears.
- **Distributed lock** for "one run per schedule" — add a Redis-shaped `Lock` seam (generalize
  `ThrottleStore`) only when a multi-instance scheduler needs it.
- **Backpressure / poison messages** — DLQ + max attempts in the outbox; alerting is ops.
- **Schedule persistence & drift** — external scheduler is simplest; in-proc APScheduler loses
  schedules on restart unless persisted.
- **Worker lifecycle** — graceful shutdown, lease expiry on crash (`locked_until` reclaim),
  at-least-once on reclaim.
- **Tenant/actor correctness** (§7) is the highest-risk integration point — get the kernel test
  in first.

---

## 18. Worked example — scheduled A ↔ B sync (no durable events needed)

```text
cron / k8s CronJob ──> `terp jobs run sync.customers.pull`
   └─> InProcessJobQueue (dev)  |  CeleryJobQueue / outbox worker (prod)
        └─> worker binds system-actor + tenant (§7), opens audited unit
             └─> SyncService.pull():
                   read System A page (cursor from last SyncRun.high_watermark)
                   for each record: upsert SyncMapping (unique key = idempotent)
                                    write target via BaseService (audited)
                                    append SyncRecordLog
                   update SyncRun counts + cursor (aggregates)
        commit once
frontend (OpenAPI client) reads: GET /sync/runs, /sync/runs/{id}/logs, /api/v1/audit
```

Switch dev→prod = pass `job_queue=CeleryJobQueue(...)` (or an Azure SB / outbox dispatcher) at
`create_app`. **Zero changes** to `SyncService`, the tables, the jobs, or the endpoints.

---

### Precedent index (so this stays Terp-native)

| New piece | Copy the shape of |
|---|---|
| `JobQueue` ABC + `InProcessJobQueue` default + `create_app(job_queue=)` | `ThrottleStore` / `InMemoryThrottleStore` (ADR 0036) |
| typed `JobCatalog` + `enqueue()` rejects non-catalog | `EventCatalog` + `emit()` (ADR 0008) |
| durable outbox as drop-in dispatcher, no call-site change | the deferred outbox in ADR 0008 |
| `require_durable_jobs` boot marker | `is_durable_audit_sink` / `require_shared_throttle_store` (ADR 0007 / 0040) |
| worker re-binds actor/tenant context | `build_audit_actor_binder` / `read_only_request` binders (ADR 0007 / 0026) |
| `jobs_reference_catalog` / `no_adhoc_background_runtime` rules | `events_reference_catalog` / `no_adhoc_middleware` (ADR 0008 / 0005) |
| `terp inspect jobs` generated surface | `terp inspect control-plane` / `terp guide rules` (ADR 0003 / 0030) |
