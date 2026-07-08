# ADR 0045 — The durable outbox: transactional, leased, retrying post-commit delivery (Phase 2)

- Status: Accepted
- Date: 2026-06-29
- Phase: async/jobs design Phase 2 (the working design doc's §9, §15 build step 2)
- Number: the async/jobs design planned this as 0044, but 0044 was taken by the
  parallel current-user `/me` work; the durable outbox is this **0045**, and the
  engine adapters / sync capability shift one number later accordingly.
- Relates to: ADR 0043 (the jobs seam — the port this makes durable), ADR 0008 (the
  event dispatcher seam, designed for exactly this drop-in), ADR 0007 / 0027
  (`terp-cap-audit` — the table-owning-capability + packaged-migration precedent this
  mirrors), ADR 0038 (the re-entrant `enter_write_unit` chokepoint the producer rides),
  ADR 0040 (`is_durable_audit_sink` / the boot-marker shape), ADR 0036 (`ThrottleStore`
  — framework-internal infra with a runtime + kernel-test second layer, no AST rule)
- Defers to later ADRs: the broker engine adapters (Celery / Azure Service Bus / Redis),
  the `terp-cap-sync` capability, and the scheduler / workflow-engine adapters

## Context

The jobs seam (ADR 0043) ships the typed port + a safe `InProcessJobQueue` that runs a
handler **inline**: zero infra, but queued work is lost on restart and never runs
off-request. A real deployment needs **durable, post-commit delivery** — background work
that survives a crash and drains on a worker — which the dispatcher seam (ADR 0008) was
explicitly designed to receive as a drop-in, with **no `enqueue` / `emit` call-site
change**. This ADR ships that mechanism as `terp-cap-outbox`, a table-owning capability
shaped like `terp-cap-audit`. Engine adapters and the sync capability stay deferred.

## Decision

### 1. `terp-cap-outbox` + the `outbox_message` table

A new opt-in **library** capability (no `terp.capabilities` ModuleSpec entry point —
nothing is auto-mounted) owns one append-only `outbox_message` table: `id`, `kind`
(`event` | `job`), `name`, `payload` (the JSON-serialized envelope), `idempotency_key`,
`status` (`pending` | `dispatched` | `dead_lettered`), `attempts`, `available_at`,
`locked_by`, `locked_until`, `created_at`, `dispatched_at`, `dead_lettered_at`,
`last_error`. A row is inserted `pending` and only ever transitions to `dispatched` or
`dead_lettered`; its payload never changes, so — like `AuditEvent` — it composes
`UUIDPrimaryKeyMixin` rather than `BaseTable` (the lease, not an OCC `version`,
arbitrates concurrent workers, and the explicit `dispatched_at` / `dead_lettered_at`
stamps are the meaningful timeline). Every caller-influenceable `str` column caps its
length. It ships an **independent, linear Alembic history** (its own
`alembic_version_outbox` table) discovered through the `terp.migrations` entry-point
group (ADR 0027).

### 2. Transactional producers (the highest-risk detail: the write guard)

`OutboxJobQueue` (a durable `JobQueue`) and `outbox_event_dispatcher` (a durable
`EventDispatcher`) both write their row **on the session they already receive** — the
business write's `WriteGuardedSession`. The risk is that this session's `add` / `commit`
**fail closed** outside the audited `BaseService` write scope. The clean resolution: the
single `store.append` rides `enter_write_unit()` (ADR 0038) — exactly like
`BaseService._save` — so the INSERT joins whatever transaction is open. Enqueued from
inside a business write (e.g. an `_after_write` hook), the outbox row **commits
atomically** with the mutation and a rollback drops **both** (no dual-write); enqueued
standalone, it is its own outermost, committed unit. `OutboxMessage` is not a `BaseTable`
so it cannot route through `BaseService`; like the durable audit sink at the base of the
write stack, it appends directly under a governed, budgeted `# arch-allow-*` marker. A
kernel test proves both directions (commit ⇒ exactly one row; the business write rolls
back ⇒ none).

### 3. The leased, retrying worker (at-least-once)

`OutboxWorker` claims a batch of **due, unlocked** rows with a single **portable atomic
UPDATE** — `SET locked_by, locked_until WHERE id IN (SELECT … WHERE pending AND
available_at ≤ now AND lease free/expired ORDER BY available_at LIMIT n)` — adding
`SELECT … FOR UPDATE SKIP LOCKED` on a backend that supports it (PostgreSQL; SQLite
silently drops the clause, the atomic UPDATE still serialises writers). A unique
per-cycle `claim_id` makes the follow-up `SELECT` return exactly the rows this worker
won, so **N workers drain one outbox** without double-dispatch. It then executes each row
— a **job** through the kernel's context-binding `run_job` (so its writes stay audited +
actor / tenant stamped, the design's §7, with the stale-envelope `JobError` handled), an
**event** through the in-process eventbus handlers — and records the outcome: `dispatched`,
a **retry** with exponential backoff per the job's `RetryPolicy`, or `dead_lettered` once
`max_attempts` is spent. Delivery is **at-least-once**: a crashed worker's lease expires
at `locked_until` and another reclaims and re-runs the row, so handlers must be idempotent
(`idempotency_key` + the business unique keys). To stay correct on SQLite (a held read
transaction blocks a writer on another connection) the worker **claims a batch, detaches
it, closes the claim session, then executes and finalizes each row in its own short
transaction** — so a long-running job never holds the bookkeeping lock open, and each job
runs in its own audited unit. Finalizing is **lease-guarded**: a job that outran its lease
may have been reclaimed and finalized by another worker, so the now-stale worker persists
its status transition only while it still holds the lease (`locked_by` matches its claim) —
otherwise it discards the outcome (a `lost` tally) rather than resurrecting a `dispatched`
row into a redundant re-dispatch or releasing a foreign lease. (Tune `lease_seconds` above
the longest expected job to avoid the redundant delivery in the first place.)

### 4. CLI + boot guard

`terp jobs worker [--app … --max-cycles … --batch-size … --lease-seconds …]` is the
worker-container entrypoint: it builds the app (so the live `JobCatalog` is configured),
then drains the outbox until empty (or a cycle bound), enabling `SKIP LOCKED` on
PostgreSQL automatically. `OutboxJobQueue` marks itself durable
(`mark_durable_job_queue`), so `create_app(require_durable_jobs=True)` — which fails the
boot closed on the in-process default (ADR 0043) — now **accepts it**, proven by a boot
test. No `terp.core` change was needed (the boot marker, `run_job`, and the write-scope
primitives already exist), so the vendored core mirror is untouched.

### Deliberately deferred (own ADRs)

The broker engine adapters (Celery / Azure Service Bus / Redis — a thin `JobQueue` per
heavy lib), the `terp-cap-sync` capability built only on the ports, and the scheduler /
workflow-engine adapters. The `no_adhoc_background_runtime` rule waits for the adapter
phase — there is still no engine to police.

## Consequences

- A deployment switches dev → durable with a one-line composition change —
  `create_app(job_queue=OutboxJobQueue(), event_dispatcher=outbox_event_dispatcher,
  require_durable_jobs=settings.is_production)` — and runs `terp jobs worker`, with **zero**
  change to any `enqueue` / `emit` call site, service, table, or handler.
- The outbox carries **both** kinds (`job` | `event`) through one table, one worker, one
  lease — the deferred "durable event outbox" from ADR 0008 and the durable jobs from ADR
  0043 land together.
- The example app is untouched (no module wires the durable queue yet) and its escape-hatch
  budget stays `{}`; the capability is inert until a consumer opts in. Installing it does add
  its table to the global migration set (the conformance gate now expects `outbox`).
- At-least-once + idempotency is the realistic contract (documented loudly); exactly-once and
  a result/status backend are explicitly out of scope.

## Enforcement (the ADR-0006 quadruple)

1. **Typed registry + safe default** — the `OutboxMessage` table + the durable, **marked**
   `OutboxJobQueue` / `outbox_event_dispatcher`; the in-process default (ADR 0043) is
   unchanged and stays the zero-infra path.
2. **Fail-closed runtime** — `append` rides the audited write unit (atomic, never an
   unaudited side-door); the claim is an atomic lease (no double-dispatch); a failing
   handler retries with backoff and dead-letters after `max_attempts`;
   `create_app(require_durable_jobs=True)` refuses any queue not marked durable.
3. **Build-time** — the capability is run through the **full `terp.arch` harness**
   (`test_capability_arch`) exactly like an app: its only violations are the governed,
   budgeted framework-infra opt-outs (the append-only table, the base-of-the-write-stack
   `session` writes, and the two `_internal` reaches into the write scope + the kernel job
   runner), each carrying a justified `# arch-allow-*` marker ratcheted by a checked-in
   escape-hatch budget. The migration is exercised end-to-end by the upgrade / downgrade /
   no-drift conformance gate, and the whole capability is under the 100% line-coverage gate
   (only the generated `migrations/versions/` is omitted). No new AST rule: the worker /
   lease / serializer are framework-internal, so — like `ThrottleStore` (ADR 0036) — the
   second layer is the fail-closed runtime + the kernel test, not a module-policing rule.
4. **Budgeted escape hatch** — the durable / adapter swap is the sanctioned opt-in, and the
   capability's governed `# arch-allow-*` markers are ratcheted by
   `packages/backend/capabilities/outbox/escape-hatch-budget.json`.

`tests/architecture/test_outbox.py` is the capability gate (transactional enqueue +
rollback atomicity, the lease / skip-active / reclaim-expired / not-yet-due / SKIP-LOCKED
claim, retry + backoff, dead-letter, at-least-once redelivery, the §7 audited /
actor-stamped worker run, the lease-guarded finalize (a stolen lease is discarded, not
clobbered), event delivery + event dead-letter, the drain loop, and the serde round-trips),
and `tests/architecture/test_cli_jobs.py` covers `terp jobs worker`.
The full suite is green at 100% line coverage.
