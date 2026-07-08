# ADR 0043 — The jobs seam: typed catalog + fail-closed `enqueue` + context-binding runner (Phase 1)

- Status: Accepted
- Date: 2026-06-29
- Phase: async/jobs design Phase 1 (the working design doc's §15, build step 1)
- Relates to: ADR 0008 (event catalog + typed `emit` + no-op dispatcher — the seam
  shape this copies), ADR 0007 (audit sink + `audit_actor_ctx`), ADR 0036
  (`ThrottleStore` + `InMemoryThrottleStore` default), ADR 0040
  (`is_durable_audit_sink` / `require_shared_throttle_store` boot markers),
  ADR 0017 (`register_scope_predicate` — the capability-plugs-into-core pattern),
  ADR 0006 (the Tier A/B/C "quadruple"), ADR 0030/0037 (rule wiring + generated
  `terp guide rules` + meta-test)
- Defers to later ADRs: durable outbox (0044), engine adapters (0045), the sync
  capability (0046), scheduler adapters / workflow engine

## Context

Terp needs background work — scheduled syncs, exports, webhooks, emails — without
baking an engine choice (Celery / Redis / Azure Service Bus / multiprocessing) into
domain code. The working design (`docs/internal/drafts/jobs-scheduler-outbox-and-sync-design.md`)
settles the strategy: **ports first, engines as adapters, sync last.** `terp.core`
defines tiny, typed, *serializable* job ports with a safe in-process default — exactly
the shape already proven by `EventDispatcher` (ADR 0008), `ThrottleStore` (ADR 0036),
and `AuditSink` (ADR 0007). Concrete engines and the durable outbox are opt-in
capability packages wired at `create_app(...)` in later ADRs.

This ADR ships **Phase 1 only: the core job seam.** It unblocks a scheduled job today
with zero broker infra (an external cron calls `terp jobs run`), and it gets the hard
part — context propagation into a request-less worker — right and tested up front,
because that is where "audited / tenant-isolated by construction" otherwise quietly
breaks.

## Decision

### 1. `terp.core.jobs` — the typed seam (layer 0, no engine imports)

A job is a typed `JobDefinition` (a dotted `name`, a `payload_schema`, a handler
resolved **by name**, a `RetryPolicy`, a `queue` routing hint, a `JobVisibility`),
indexed in a `JobCatalog` that rejects duplicate names — mirroring `EventDefinition` /
`EventCatalog` exactly. What crosses the wire is a JSON-serializable `JobEnvelope`
(`name`, `payload`, `idempotency_key`, `actor_id`, `tenant_id`, `request_id`,
`enqueued_at`, `attempt`). A `JobQueue` ABC has one method, `enqueue(session, envelope)
-> id`; the safe default `InProcessJobQueue` runs the handler **inline** in its own
audited unit (no `threading` — the layer-0 boundary forbids a runtime thread in core).

The single producer chokepoint is `enqueue(session, *, job, payload,
idempotency_key=None)` — the job analogue of `emit`: it accepts only a typed
`JobDefinition`, resolves the **canonical** catalog entry, and **fails closed** on an
unknown name *or* a same-name shadow (`JobError`), validates the payload against the
catalog's schema (round-tripped through `model_dump(mode="json")`, so no ORM rows or
Python objects ride the wire), and captures the originating actor / tenant / request id
into the envelope.

### 2. Context propagation (the design's §7 — the highest-risk detail)

The worker / scope opener lives under `terp.core._internal.job_runtime` (a module
**cannot** import it — `no_internal_imports`); only a `JobQueue` drives it. `run_job`:

- resolves the job from the **active catalog by name** (fail closed if a stale envelope
  names a job a deploy has since removed — the handler is never trusted from the wire),
- re-binds the envelope's `actor_id` — or, when no user originated the work, a
  configured **system actor** (a control-plane default, Tier B, so stamping is never
  silently `None` in production) — plus `request_id`, and `tenant_id` through a new
  registered seam, and
- runs the handler inside a fresh, write-guarded session **with a reset write scope**.

That last point is the subtle, security-relevant one. The in-process queue runs a
handler *inline in the caller's context*, so a job enqueued from inside an audited write
(e.g. an `_after_write` hook) would otherwise inherit the enclosing `_write_depth > 0`
and the read-only-request flag from the ContextVars they live in: its own `_save` would
treat itself as *nested* and defer the single commit to an "outer" unit on a **different**
session that never commits it — a **silently lost, unaudited write** — or be wrongly
refused during a safe (GET) request. `run_job` opens `fresh_write_scope()` (depth 0,
write-closed, not read-only) so the job is always its **own** outermost, independent,
audited unit at the envelope's authority. A regression test drives exactly this case.

So **every write a job makes is still audited and actor / tenant stamped** with no
special-casing — the `BaseService` chokepoint just works. The tenant seam
(`register_job_tenant_context(read=…, bind=…)`) is the job-side analogue of
`register_scope_predicate` (ADR 0017): a scope capability supplies how to *capture* the
tenant at enqueue and *re-bind* it at run, so the kernel never imports tenancy. Like a
scope predicate it is a capability registration (persistent across composed apps,
reset only by its own `reset_job_tenant_context`), not per-app runtime. A handler chains
follow-up work through the same typed `enqueue` chokepoint — `JobContext` deliberately
exposes **no raw queue**, so even chained jobs carry the no-drift guarantee.

### 3. `create_app` wiring + boot guards

`create_app(..., job_queue=None, require_durable_jobs=False)`: the catalog lives on
`ControlPlane.jobs` (the stand-in actor on `ControlPlane.job_system_actor_id`), every
declared `ModuleSpec.jobs` is boot-validated against it (an undeclared job fails the
boot, like a policy / event reference), and `require_durable_jobs=True` fails the boot
closed unless the wired `job_queue` is a backend marked durable via
`mark_durable_job_queue` — mirroring `is_durable_audit_sink` /
`require_shared_throttle_store` (ADR 0040). The in-process default is deliberately
*unmarked* (it loses queued work on restart).

### 4. CLI

`terp jobs run <name> --payload <json>` is the most abstract possible scheduler (any
cron / k8s CronJob / timer invokes it): it builds the app, resolves the named job,
validates the JSON payload, and enqueues it. `terp jobs list` / `terp inspect jobs`
render the catalog straight from the control plane — generated, so the listing cannot
drift from what the app runs. `terp guide jobs` teaches the authoring recipe (declare a
typed job, enqueue through the chokepoint, pass ids not entities, the system actor + the
durable boot guard), alongside the auto-generated `terp guide rules`.

### Deliberately deferred (own ADRs)

The durable outbox (transactional `outbox_message` table + leased retrying worker +
`terp jobs worker`), the engine adapters (Celery / Azure SB / Redis), the scheduler
adapters (APScheduler / Celery-beat), the workflow-engine port, and the `terp-cap-sync`
capability. The `no_adhoc_background_runtime` rule is deferred to the adapter phase —
there is no engine to police yet.

## Consequences

- A scheduled job works **today** with only core + an external cron, zero broker.
- in-process → durable → Celery / Azure swaps with **no `enqueue` call-site change**
  (the design's promise), because the call site speaks only the typed port.
- The example app is untouched (no module declares a job yet) and its escape-hatch
  budget stays `{}`; the seam is inert until a consumer opts in.
- The in-process default runs a handler inline (synchronously), not on a threadpool —
  a deployment needing real off-request execution wires a durable / broker adapter.
  At-least-once + idempotency is the realistic model the later phases formalize.

## Enforcement (the ADR-0006 quadruple)

1. **Typed registry + safe default** — `JobCatalog` / `JobDefinition` + the
   `InProcessJobQueue` default.
2. **Fail-closed runtime** — `enqueue` rejects an unregistered / shadowed job
   (`JobError`); `create_app` boot-validates `ModuleSpec.jobs` against the catalog and
   refuses a non-durable queue when `require_durable_jobs=True`; `run_job` re-binds the
   actor (system-actor fallback) and tenant so a job's writes stay audited + isolated.
3. **Build-time** — the new `terp.arch` `jobs_reference_catalog` rule (paired with a
   meta-test, surfaced automatically in `terp guide rules`) forbids a bare-string or
   inline-literal job in `enqueue(job=…)` / `ModuleSpec(jobs=…)`.
4. **Budgeted escape hatch** — the durable / adapter swap and the
   `# arch-allow-jobs_reference_catalog` marker (ratcheted by the escape-hatch budget).

`tests/architecture/test_jobs.py` is the kernel gate, including the §7 proof — a job's
writes are **audited and actor / tenant stamped from the envelope, tenant-isolated, with
the system-actor fallback** — plus catalog dup-reject, fail-closed enqueue (unknown /
shadow / bad payload), the raising-handler path, the boot guards, and a **write-scope
regression** (a job enqueued from inside an audited write / a read-only request still
commits as its own audited unit). `tests/architecture/test_cli_jobs.py` covers the CLI.
The vendored core mirror (`vendor/terp-core/`) includes `jobs.py` + `_internal/job_runtime.py`
byte-exact (`test_vendored_core_unmodified`); the 100% line-coverage gate is unchanged (595 passing).
