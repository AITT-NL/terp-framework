# ADR 0046 — The first engine adapter: `terp-cap-jobs-celery` + the `no_adhoc_background_runtime` rule (Phase 3)

- Status: Accepted
- Date: 2026-06-30
- Phase: async/jobs design Phase 3 (the working design doc's §10, §15 build step 3)
- Number: the async/jobs design sketched this as 0045, but the durable outbox took 0045
  (after the parallel `/me` work took 0044); this first **engine adapter** is 0046, and the
  sync capability / scheduler adapters shift one number later accordingly.
- Relates to: ADR 0043 (the jobs seam — the port this proves engine-agnostic), ADR 0045
  (`terp-cap-outbox` — the table-owning durable cap whose package shape, durable marker, and
  `run_job` reuse this mirrors), ADR 0008 (the `EventDispatcher` seam — the same ports-first
  shape), ADR 0040 (`is_durable_audit_sink` / the boot-marker pattern `mark_durable_job_queue`
  follows), ADR 0030/0037 (rule wiring + generated `terp guide rules` + the meta-test pairing)
- Defers to later ADRs: the `terp-cap-sync` consumer capability (0047), the scheduler seam +
  adapters and the workflow-engine port (0048+), and the Azure Service Bus / Redis adapters

## Context

The jobs seam (ADR 0043) and the durable outbox (ADR 0045) are both pure-Python: the seam
runs a handler inline, the outbox persists it for a leased worker. Neither proves the
central promise of the design — that the engine which *actually runs* background work
(Celery / Azure Service Bus / Redis) is a **composition-root choice**, swappable with
**zero domain change**, never an import baked into a service. The design's §15 makes the
**first real engine adapter** the next step precisely because it is the proof (like a
second tenancy consumer proves tenancy): if a thin `JobQueue` over a heavyweight broker
drops in with no `enqueue` call-site change, the seam is genuinely abstract.

Celery is the first target (a deployment choice; the others follow the same shape). Shipping
an engine adapter also, for the first time, introduces a heavyweight background dependency
into the workspace — so this ADR ships the **`no_adhoc_background_runtime` rule alongside it**,
so the new engine can never leak into app code (the design's §12).

## Decision

### 1. `terp-cap-jobs-celery` — a thin, durable `JobQueue` over Celery

A new opt-in **library / engine-adapter** capability (no `terp.capabilities` ModuleSpec
entry point, no tables, no `terp.migrations` entry point — nothing is auto-mounted; depends
only on `terp-core` + `celery`). It supplies the two halves of a Celery deployment:

- **Producer** — `CeleryJobQueue(celery_app)`: `enqueue(session, envelope)` serializes the
  whole `JobEnvelope` to JSON `kwargs` and `celery_app.send_task(TERP_JOB_TASK, kwargs=…,
  queue=…)`, routed to the `JobDefinition`'s `queue` hint resolved from the **live catalog**
  (so a job's queue travels with its definition). It returns Celery's task id and marks
  itself durable (`mark_durable_job_queue`), so `create_app(require_durable_jobs=True)`
  accepts it where the in-process default is refused.
- **Consumer** — `register_terp_worker(celery_app)`: registers **one** canonical Terp task
  (`TERP_JOB_TASK = "terp.jobs.run"`), not one Celery task per job, so the Celery registry
  can never drift from the `JobCatalog`. The task rebuilds the envelope and runs it through
  the kernel's context-binding `terp.core._internal.job_runtime.run_job` — re-binding the
  envelope's `actor_id` / `tenant_id` / `request_id` (the design's §7, with the configured
  system-actor fallback), so **every write a job makes stays audited + actor / tenant
  stamped** under Celery exactly as inline. The handler is resolved **by name** through the
  active catalog (a stale envelope after a deploy fails closed with `JobError`); the job's
  `RetryPolicy` maps onto Celery's own retry (exponential backoff until `max_attempts`, then
  propagate), so the retry budget travels with the `JobDefinition` rather than being
  re-specified per broker.

One canonical task + name-based handler resolution is the key no-drift choice: the engine
carries only the envelope, and Terp's catalog stays the single source of truth — the same
property that lets in-process → outbox → Celery swap untouched.

**Transactionality caveat (documented, not hidden).** `send_task` publishes to the broker
immediately, **not** on the caller's DB transaction — a job enqueued inside a business write
is delivered even if that write later rolls back (a dual-write hazard). For
transactional-with-the-commit capture, wire `OutboxJobQueue` (ADR 0045) as the `JobQueue`
and relay outbox rows to Celery; this direct adapter is the simplest path for jobs that
tolerate at-least-once delivery plus that post-enqueue-rollback edge (the design's §10 /
§17). "Durable" here means **restart-surviving** (a persistent broker holds the message) —
the precise property `require_durable_jobs` checks — not transactional atomicity, which is
the outbox's distinct guarantee.

### 2. The `no_adhoc_background_runtime` rule (the new control's build-time half)

App modules must not import a background **engine** directly — `celery` / `azure.servicebus`
/ `redis` / `apscheduler` (and a submodule of one) — nor a raw `threading` /
`multiprocessing` **execution** construct (`Thread` / `Process` / a pool, or a bare
`import threading` that can reach one). Background work flows through the typed
`terp.core.enqueue` chokepoint and the active `JobQueue`, so the engine stays an opt-in
adapter wired at the composition root. The rule is deliberately **precise** (the harness's
contract): a pure **synchronization primitive** imported by name — `from threading import
RLock` — is a correctness tool, not background execution, and stays allowed (so the `users`
cap's last-admin lock is not a false positive). An adapter capability legitimately imports
its engine under a budgeted `# arch-allow-no-adhoc-background-runtime` marker — which is
exactly how `terp-cap-jobs-celery` reaches Celery (two markers, ratcheted by its
`escape-hatch-budget.json`).

It is wired the standard way (ADR 0030/0037): `rules/imports.py` + the `rules/__init__.py`
`_ALL_RULES`/`__all__` + `arch/__init__.py`, paired with `test_no_adhoc_background_runtime`,
and surfaced automatically in the generated `terp guide rules`. Its runtime half is the
jobs seam itself: every job runs through `enqueue` and the active queue, so an adapter swap
never touches a call site.

### 3. Testing without a broker, and the coverage boundary

The adapter wraps a heavyweight broker lib whose delivery paths only exercise against real
infrastructure, so — like the broker adapters the design's §16 places in their own packages
— it ships **its own suite** (`tests/architecture/test_jobs_celery.py`) and is **omitted
from the core `--cov=terp` 100% gate** (the one engine adapter exception, documented in the
coverage `omit`). Its suite runs the **real** producer + the **real** registered worker task
over a real in-memory engine, with only the broker transport simulated (a `Celery` subclass
whose `send_task` dispatches the registered task locally — `task_always_eager` is ignored by
`send_task`). It proves: the producer ships the canonical task routed by the catalog queue;
the worker re-binds actor + tenant from the envelope so the write is audited + stamped (§7),
with the system-actor fallback; the **in-process → Celery swap produces identical effects
with zero domain change**; the durable marker boots under `require_durable_jobs=True`; and
the `RetryPolicy` → Celery-retry mapping (a testable worker core split out from the
one-line, engine-coupled `self.retry`).

### Deliberately deferred (own ADRs)

The `terp-cap-sync` consumer capability built only on the ports (0047), the scheduler seam +
APScheduler / Celery-beat adapters and the workflow-engine port (0048+), and the further
broker adapters (Azure Service Bus / Redis — each the same thin `JobQueue` shape).

## Consequences

- A deployment switches in-process → Celery with a one-line composition change —
  `create_app(job_queue=CeleryJobQueue(celery_app), require_durable_jobs=settings.is_production)`
  in the producer, `register_terp_worker(celery_app)` in the worker — with **zero** change to
  any `enqueue` call site, service, table, or handler. The seam is proven engine-agnostic.
- No `terp.core` change was needed (the boot marker, `run_job`, and the context binding
  already exist), so the **vendored core mirror is untouched**.
- The example app is untouched (no module wires Celery) and its escape-hatch budget stays
  `{}`; the adapter is inert until a consumer opts in. Installing it adds `celery` to the
  resolved workspace.
- A new universal control — `no_adhoc_background_runtime` (the 32nd rule) — keeps every
  future engine (Azure SB / Redis / APScheduler) out of app code from the moment its
  dependency could appear.

## Enforcement (the ADR-0006 quadruple)

1. **Typed registry + safe default** — the in-process default (ADR 0043) is unchanged and
   stays the zero-infra path; `CeleryJobQueue` is the durable, **marked** opt-in.
2. **Fail-closed runtime** — the worker resolves the handler from the active catalog by name
   (stale envelope ⇒ `JobError`), re-binds actor / tenant so a job's writes stay audited +
   isolated, and maps the `RetryPolicy` onto Celery's retry; `create_app(require_durable_jobs=
   True)` refuses any queue not marked durable.
3. **Build-time** — the new `terp.arch` `no_adhoc_background_runtime` rule (paired with a
   meta-test, surfaced in the generated `terp guide rules`) forbids a background engine /
   ad-hoc thread import in app code; the capability is run through the **full harness**
   (`test_capability_arch`) like an app, its only violations the governed, budgeted engine /
   `_internal` opt-outs, each a justified `# arch-allow-*` ratcheted by a checked-in budget.
4. **Budgeted escape hatch** — the adapter swap is the sanctioned opt-in, and the
   capability's `# arch-allow-*` markers are ratcheted by
   `packages/backend/capabilities/jobs_celery/escape-hatch-budget.json`.

`tests/architecture/test_jobs_celery.py` is the capability gate (producer routing, the §7
audited / actor- + tenant-stamped worker run with the system-actor fallback, the in-process →
Celery zero-domain-change swap, the durable-marker boot guard, the retry mapping, and the
serde round-trip), and `tests/architecture/test_arch_harness.py::test_no_adhoc_background_runtime`
the rule gate. The full `--cov=terp` suite is green at 100% line coverage (the engine adapter
omitted, like the design's §16 broker adapters); ruff and import-linter pass.
