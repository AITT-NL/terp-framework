# ADR 0048 — Scheduler engine adapters: `terp-cap-scheduler-apscheduler` + `terp-cap-scheduler-celery-beat`

- Status: Accepted
- Date: 2026-07-01
- Phase: async/jobs design Phase 4 (the working design doc's §11, §15 build step 5)
- Relates to: ADR 0047 (the scheduler seam — the port these fill), ADR 0046 (the first engine
  adapter — the same library-cap / governed-marker / omitted-from-cov shape), ADR 0043 (the
  jobs seam a schedule fires through), ADR 0037 (`no_adhoc_background_runtime` — the rule these
  reach their engine behind)
- Defers to later ADRs: the `terp-cap-sync` consumer capability, the workflow-engine port, and
  the further job engine adapters (Azure Service Bus / Redis)

## Context

The scheduler seam (ADR 0047) ships the typed port — `ScheduleDefinition` / `ScheduleCatalog`
/ `Scheduler` ABC / `trigger_schedule` — with the external-trigger default (any cron invokes
the CLI). This ADR ships the two concrete **engine adapters** the design's §11 names, so a
deployment can run schedules with an in-process scheduler *or* the Celery-beat it already
operates — swapping with **zero domain change**, exactly like the Celery job adapter (ADR
0046). They are the follow-up ADR 0047 explicitly handed off.

## Decision

Two opt-in **library / scheduler-engine-adapter** capabilities (no `terp.capabilities`
ModuleSpec entry point, no tables — nothing auto-mounts; each depends only on `terp-core` + its
engine). Both fill the `Scheduler` ABC and fire a schedule by **enqueuing its job through the
typed chokepoint** (`trigger_schedule`), so the job flows through the active `JobQueue`
(in-process / outbox / Celery) and the context-binding runner — a user-less scheduled job runs
as the configured system actor, its writes audited + stamped, with **no special-casing**.

### 1. `terp-cap-scheduler-apscheduler` (in-process)

`ApschedulerScheduler(session_factory, scheduler=None)`: `register` adds a cron job to an
APScheduler instance (default `BackgroundScheduler`; a dedicated scheduler process may inject a
`BlockingScheduler`) whose tick opens a session and calls `trigger_schedule`. The cron is
parsed by APScheduler's `CronTrigger.from_crontab`, so a malformed cron fails at registration.
`start` / `shutdown` drive the underlying engine. It runs **in one process with no distributed
lock** — a multi-instance deployment uses Celery beat / an external scheduler / a single leader
to avoid duplicate ticks (the design's §17).

### 2. `terp-cap-scheduler-celery-beat`

`CeleryBeatScheduler(celery_app, session_factory)`: for each schedule it registers a small
**tick task** (`terp.schedule.<name>`) on the Celery app and a `beat_schedule` entry that runs
it on the schedule's cron (translated to a Celery `crontab` from the portable 5-field form);
`install` merges the `beat_schedule` onto the app config, after which `celery -A … beat` fires
the ticks (and a worker runs the enqueued jobs). Routing through a **tick task** rather than
beat sending a fixed message keeps the schedule's `payload_factory` **dynamic** per fire and
the no-drift `enqueue` validation in force.

**Deployment note:** the tick tasks are registered on the Celery app *in the calling process*,
so every Celery **worker** that runs them must be bootstrapped identically — import the
composition root that builds the app (`create_app`, configuring the live `JobCatalog` /
`JobQueue`) and call `register_all` — or beat will publish `terp.schedule.*` a worker cannot
resolve. A convenience CLI/bootstrap wrapper is deferred (see below).

One canonical property across both: the engine only *triggers*; the job is always resolved and
enqueued through Terp's typed seam, so the catalog stays the single source of truth and the
same schedule fires identically whichever adapter (or the external-cron default) is wired.

### 3. Package shape + enforcement

Each mirrors the Celery job adapter (ADR 0046): a `src/` hatchling library cap with `py.typed`,
its engine imported **only** behind the seam under a governed
`# arch-allow-no-adhoc-background-runtime` marker (two per cap), ratcheted by its
`escape-hatch-budget.json`; run through the full `terp.arch` harness via `test_capability_arch`;
added to the workspace members and **omitted from the core `--cov=terp` gate** (a heavy engine's
scheduling paths only exercise against real infrastructure — its own suite,
`tests/architecture/test_scheduler_adapters.py`, proves correctness broker-free: a fake
APScheduler that captures the registered job, and a real Celery app whose tick task is invoked
directly, each shown to reach the active `JobQueue`).

### Deliberately deferred (own ADRs)

The `terp jobs scheduler` long-running CLI entry point (a scheduler-process wrapper around
`ApschedulerScheduler`), the `terp-cap-sync` consumer capability, the workflow-engine port, and
the Azure SB / Redis job adapters.

## Consequences

- A deployment runs schedules in-process (`ApschedulerScheduler(...).register_all(
  active_schedule_catalog()).start()`) or via its Celery stack (`CeleryBeatScheduler(...)
  .register_all(...).install()` + `celery … beat`) — **no domain change**, the schedule is the
  same typed catalog constant.
- No `terp.core` change (the seam already exists), so the **vendored core mirror is untouched**.
- The example app is untouched; its escape-hatch budget stays `{}`. Installing the adapters adds
  `apscheduler` / `celery` to the resolved workspace, not to any app module.

## Enforcement (the ADR-0006 quadruple)

1. **Typed registry + safe default** — the external-trigger default (ADR 0047) is unchanged;
   these are the durable in-process / beat opt-ins filling the `Scheduler` ABC.
2. **Fail-closed runtime** — a schedule fires through `trigger_schedule` → the typed `enqueue`
   (so a scheduled job's writes stay audited + system-actor stamped); a malformed cron is
   rejected at registration (both adapters).
3. **Build-time** — the `no_adhoc_background_runtime` rule keeps the engines out of app code
   (the adapters carry the only governed, budgeted `# arch-allow-*` opt-outs, ratcheted per
   cap); the caps run through the full `terp.arch` harness; the adapter suite proves the
   in-process / beat tick reaches the active queue.
4. **Budgeted escape hatch** — the adapter swap is the sanctioned opt-in; each cap's engine
   import is a ratcheted `# arch-allow-no-adhoc-background-runtime` marker.

`tests/architecture/test_scheduler_adapters.py` is the capability gate; the scheduler adapters
are **omitted from the `--cov=terp` gate** (like the ADR 0046 job adapter), so they do not
affect the framework coverage number. Their broker-free suite proves the tick reaches the active
`JobQueue`; ruff and import-linter pass.
