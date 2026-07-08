# ADR 0047 — The scheduler seam: typed `ScheduleDefinition`/`ScheduleCatalog` + `Scheduler` port (core)

- Status: Accepted
- Date: 2026-06-30
- Phase: async/jobs design Phase 4 prerequisite (the working design doc's §11)
- Relates to: ADR 0043 (the jobs seam — a schedule references a typed `JobDefinition` and
  fires by enqueuing through it), ADR 0008 (the `EventCatalog` / typed-`emit` no-drift shape
  this mirrors), ADR 0036 (`ThrottleStore` — framework infra whose second layer is the boot
  check + kernel test, not an AST rule), ADR 0034 (the vendored-core mirror this refreshes),
  ADR 0046 (the first engine adapter — the same ports-first pattern)
- Defers to a follow-up ADR: the **scheduler engine adapters** (APScheduler in-process,
  Celery beat) as opt-in library capabilities, and the `terp jobs schedule / scheduler` CLI.
  This ADR ships **only the core port** so both adapters (and the `terp-cap-sync` schedule)
  build on one validated seam.

## Context

`terp-cap-sync` and any scheduled background work need to declare "enqueue this job on this
cron" as typed, boot-validated configuration — not a bare string wired into an engine. The
working design (§11) settles the shape: a tiny `Scheduler` **port** in `terp.core` with the
same no-drift guarantee the jobs / event catalogs already enforce, and concrete schedulers
(APScheduler, Celery beat, an external cron) as opt-in adapters. The safe default needs no
scheduler infra at all — an external cron invokes the CLI, which enqueues through the typed
chokepoint.

This ADR ships **only the core seam**. The engine adapters are handed off to a follow-up ADR
(built as separate library capabilities, like the Celery job adapter of ADR 0046), so this
foundation is committed once and both adapters — and the sync capability's schedule — depend
on a single, validated port rather than racing to define it.

## Decision

### 1. `terp.core.scheduling` — the typed seam (layer 0, no engine imports)

- `ScheduleDefinition(name, job, cron, payload_factory=None)` — a dotted `name`, a typed
  `JobDefinition` (never a bare string), an **opaque** `cron` string (the kernel imports no
  cron parser — layer 0; an adapter parses it), and a `payload_factory` producing the payload
  to enqueue each tick (`None` → the job's empty/default payload). It validates its own shape.
- `ScheduleCatalog` — indexes schedules by name, rejects duplicates, and `missing_jobs(
  job_catalog)` returns any schedule whose job is not the catalog's canonical entry (matched
  by value, so a same-name *shadow* job is caught) — exactly mirroring `JobCatalog`.
- `Scheduler` ABC — one abstract `register(schedule)` plus a concrete `register_all(catalog)`;
  the single method an engine adapter fills. The kernel never runs a scheduler (a scheduler is
  a separate process, like the outbox worker).
- `trigger_schedule(session, schedule)` — fires a schedule once by building its payload and
  **enqueuing its job through the typed `enqueue` chokepoint**, so it flows through the active
  `JobQueue` (in-process / outbox / broker) and the context-binding runner. A scheduled job
  has no originating user, so it runs as the configured **system actor** and its writes stay
  audited + stamped — no special-casing. `payload_factory` is re-evaluated each tick, so a
  "now"-dependent payload stays fresh.
- `configure_schedules` / `active_schedule_catalog` / `reset_schedules_runtime` — the runtime
  accessors, mirroring `configure_jobs` (kept on `terp.core.scheduling`, not re-exported, like
  the jobs runtime accessors); the public surface re-exports `ScheduleDefinition` /
  `ScheduleCatalog` / `Scheduler` / `trigger_schedule`.

### 2. `create_app` wiring + boot validation

`ControlPlane` gains a `schedules: ScheduleCatalog`. `create_app` calls `configure_schedules(
resolved_plane.schedules)` beside `configure_jobs`, and the control plane's
`validation_errors` now also checks every schedule's job against the `JobCatalog` — so a
schedule enqueuing an undeclared (or shadowed) job **fails the boot**, exactly like a policy /
event / job reference. There is no module-authored schedule string to police, so (like the
throttle store, ADR 0036) the build-time half is this boot check + the kernel test, **not** a
new `terp.arch` AST rule.

### 3. Safe default + the vendored mirror

The default is the design's **external trigger** (§8): with zero scheduler infra, any cron /
k8s CronJob / systemd timer / Azure timer fires a schedule (a follow-up adds the
`terp jobs schedule` CLI as the convenient entry point). Because this changes `terp.core`
(a new `scheduling.py` + the `ControlPlane` / `create_app` / `__init__` wiring), the
`vendor/terp-core/` mirror is refreshed byte-exact and `test_vendored_core_unmodified` stays
green.

### Deliberately handed off (a follow-up ADR)

The **scheduler engine adapters** — `terp-cap-scheduler-apscheduler` (in-process) and
`terp-cap-scheduler-celery-beat` — as opt-in library capabilities that import their engine
behind the seam under a governed `# arch-allow-no-adhoc-background-runtime` marker (each with
its own suite, omitted from the core `--cov=terp` gate, like the Celery job adapter), plus the
`terp jobs schedule <name>` / `terp jobs scheduler` CLI generated from the live catalog.

## Consequences

- A scheduled job works **today** with only core + an external cron — zero scheduler infra.
- `terp-cap-sync`'s schedule and both scheduler adapters build on **one** validated port; the
  seam is committed once so concurrent adapter work cannot diverge on the core types.
- in-process → APScheduler → Celery beat swaps with **no domain change** (the schedule is the
  same typed catalog constant; only the wired adapter differs).
- The example app is untouched (no schedule declared) and its escape-hatch budget stays `{}`.

## Enforcement (the ADR-0006 quadruple)

1. **Typed registry + safe default** — `ScheduleCatalog` / `ScheduleDefinition` + the
   external-trigger default (no engine required).
2. **Fail-closed runtime** — `ScheduleDefinition` rejects a non-`JobDefinition` job / bad
   name / empty cron; `create_app` boot-validates every schedule's job against the
   `JobCatalog` (`BootError` on drift); `trigger_schedule` enqueues through the typed
   chokepoint, so a scheduled job's writes are audited + system-actor stamped.
3. **Build-time** — the boot validation + the kernel gate (`tests/architecture/test_scheduling.py`):
   catalog dup-reject, `missing_jobs` (including a shadow job), shape validation, `register_all`,
   `trigger_schedule` payload (factory + default), the runtime accessors, the control-plane
   validation, and the `create_app` boot guard. No AST rule (no module-authored pattern to police).
4. **Budgeted escape hatch** — the adapter swap is the sanctioned opt-in; there is no marker
   here (the seam adds no app-module opt-out).

The vendored core mirror includes `scheduling.py` byte-exact (`test_vendored_core_unmodified`);
`terp.core` stays at 100% line coverage.
