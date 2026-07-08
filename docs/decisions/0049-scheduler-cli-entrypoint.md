# ADR 0049 — The `terp jobs scheduler` CLI: the in-process scheduler-process entrypoint

- Status: Accepted
- Date: 2026-07-01
- Phase: async/jobs design Phase 4 (the working design doc's §11, §13)
- Relates to: ADR 0048 (the scheduler engine adapters — this is the deferred CLI wrapper they
  named), ADR 0047 (the scheduler seam it drives), ADR 0043 (`terp jobs run`) / ADR 0045
  (`terp jobs worker`) — the sibling CLI entrypoints this mirrors
- Closes: the one item ADR 0048 explicitly deferred ("the `terp jobs scheduler` long-running
  CLI entry point")

## Context

ADR 0047 shipped the scheduler seam and ADR 0048 the APScheduler / Celery-beat adapters, but
deferred the convenience **scheduler-process entrypoint**. Until now a deployment had to hand-wire
`ApschedulerScheduler(...).register_all(active_schedule_catalog()).start()` in a composition
root. This ADR ships that wiring as `terp jobs scheduler`, the sibling of `terp jobs run` (the
external trigger) and `terp jobs worker` (the outbox drainer), so a scheduler process is a
one-line container command.

## Decision

`terp jobs scheduler [--app … --app-root …]` (`run_scheduler_command`) builds the app — so
`create_app` configures the live `ScheduleCatalog` (and the `JobCatalog` its jobs resolve
against) — then registers every declared schedule with an APScheduler-backed `Scheduler` and
**starts it**. Each cron tick fires the schedule through the typed `enqueue` chokepoint, so a
scheduled job flows through the active `JobQueue` and the context-binding runner (audited +
system-actor stamped); with the durable outbox wired, `terp jobs worker` runs it off-request.
`start` **blocks** until the process is stopped (SIGINT) — a daemon, like any scheduler.

The concrete scheduler is **injectable** (`run_scheduler_command(scheduler=…)`): the default
`_default_scheduler()` wraps APScheduler's `BlockingScheduler` (whose `start` blocks the main
thread) via `terp-cap-scheduler-apscheduler`, resolved lazily so the CLI keeps no hard
dependency on the adapter (mirroring how `terp jobs worker` lazily imports `terp-cap-outbox`).
Injection is what keeps the daemon unit-testable: the suite drives the command with a
non-blocking fake scheduler and covers the real factory + the `main` dispatch separately, so
`terp.cli` stays at 100% coverage without ever entering the blocking loop.

The guide topic (`terp guide jobs`) gains the schedule-authoring recipe (declare a
`ScheduleDefinition` on `ControlPlane(schedules=…)`, run it with `terp jobs scheduler` or Celery
beat). This is not a new seam or control — it is the CLI surface of the already-decided ADR
0047/0048 mechanism — so it adds **no** `terp.core` change (no vendored-mirror touch) and **no**
new `terp.arch` rule.

### Deliberately still deferred

Multi-instance scheduler leader-election / a distributed lock (single-process APScheduler has
none — use Celery beat or a single leader; the design's §17), and the `terp-cap-sync` consumer
capability that will declare the first real schedule.

## Consequences

- A scheduler process is now `terp jobs scheduler` — no composition-root code. `terp jobs
  run` / `worker` / `scheduler` are the three async entrypoints (external trigger / outbox
  drainer / cron daemon).
- The scheduler slice (seam + adapters + CLI) is complete; only a real consumer
  (`terp-cap-sync`) and multi-instance leadership remain.
- The example app is untouched (it declares no schedule); its escape-hatch budget stays `{}`.

## Enforcement (the ADR-0006 quadruple)

1. **Typed registry + safe default** — the schedules come from the boot-validated
   `ScheduleCatalog` (ADR 0047); the external-trigger default (`terp jobs run` from cron) is
   unchanged.
2. **Fail-closed runtime** — the CLI enqueues through the typed chokepoint (a scheduled job's
   writes stay audited + system-actor stamped); a schedule referencing an undeclared job already
   fails the boot the CLI performs.
3. **Build-time** — `tests/architecture/test_cli_jobs.py` covers the command (register + start
   via a fake), the default APScheduler factory, and the `main` dispatch; `terp.cli` holds 100%
   line coverage.
4. **Budgeted escape hatch** — none needed: the CLI adds no app-module opt-out (the engine stays
   inside the adapter, lazily imported).

The full `--cov=terp` suite is green at 100% line coverage (721 passing); ruff and import-linter
pass.
