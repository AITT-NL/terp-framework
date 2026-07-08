# ADR 0050 — `terp-cap-sync`: reconcile a local entity against an external system on the shipped seams

- Status: Accepted
- Date: 2026-07-01
- Phase: async/jobs design Phase 5 — the headline **consumer** capability (the working design
  doc's §14–18)
- Relates to: ADR 0043 (the jobs seam — the reconcile runs as a typed `JobDefinition` the
  runner executes post-commit), ADR 0045 (the durable outbox — a failed reconcile retries /
  dead-letters through it), ADR 0047 (the scheduler seam — a sync fires on a
  `ScheduleDefinition`), ADR 0048/0049 (the scheduler adapters + CLI that drive it), ADR 0051
  (webhooks — the sibling consumer cap this mirrors for structure: models + append-only log +
  admin router + `terp.migrations` history), ADR 0013 (the `identity` library-cap precedent —
  a `terp.migrations` entry point but **no** `terp.capabilities` auto-discovery), ADR 0007
  (audit — the append-only sink whose `# arch-allow-*` posture the record log reuses)
- Adds **no** new `terp.core` surface and **no** engine: it is built entirely on ports that
  already shipped, so the vendored core mirror is untouched.

## Context

The async design ends with the piece that proves the seams carry real weight: a maintained,
secure-by-default **sync** — reconcile a local entity type against an external system (a CRM,
an ERP, an upstream service) — that an app configures rather than hand-builds. The design (§14)
fixes the shape: the two hard problems (which record won on a conflict; how a background read
of System B stays out of the request write path) are solved **once** in the capability, and the
app supplies only a thin `SyncSource`. Everything else — run bookkeeping, the identity ledger,
the record log, retry, scheduling — is the framework's, on the jobs / outbox / scheduler ports.

Two invariants drive every decision (§14, echoing the ADR-0040 dual-write review):

1. the **external read** of System B happens in the **job handler** (a worker, *post-commit*),
   never in an `_after_write` hook that would couple an outbound call to the request
   transaction; and
2. the **local write** goes through an audited `BaseService`, so a synced row is actor / owner
   stamped and audited exactly like any hand-entered row.

## Decision

Ship `terp-cap-sync` (dist `terp-cap-sync`, package `terp.capabilities.sync`) depending only on
`terp-core`.

### 1. The `SyncSource` seam (the app's only obligation)

An ABC keyed by `entity_type`, resolved from a small process-global registry
(`register_sync_source` / `resolve_sync_source`, fail-closed on an unregistered type — the job
carries the *name*, not a closure, so a remote worker resolves it like a job handler):

- `pull(cursor) -> RemotePage` — read one page of remote records (the external System-B call,
  invoked inside the handler). `RemoteRecord(remote_id, checksum, payload)` carries a
  change-detecting checksum + JSON scalars (ids, not entities).
- `apply(session, record, local_id) -> uuid` — create (`local_id is None`) or update the local
  row **through an audited `BaseService`**; returns its id.
- `push(session) -> int` — the outbound direction, **unsupported by default** (a pull-only
  source fails closed); a push-capable source overrides it.

### 2. Three tables (mirroring the webhooks split)

- `SyncMapping` (`BaseTable`) — the identity ledger, unique on `(entity_type, local_id)` **and**
  `(entity_type, remote_id)`, so an upsert is idempotent from either side: the natural
  at-least-once dedupe key.
- `SyncRun` (`BaseTable`) — one reconcile attempt's status, counts, and high-watermark `cursor`,
  stored so a stats view never pays a per-row `COUNT(*)`.
- `SyncRecordLog` — one **append-only** line per record (a `UUIDPrimaryKeyMixin` immutable row
  like `AuditEvent`), written by the one governed `store.py` that rides the audited write unit.

### 3. The reconcile engine (`SyncService`, a `BaseService[SyncMapping, …]`)

`pull(session, source)` opens a `SyncRun` (resuming from the last **succeeded** run's cursor),
pulls a page, and for each record looks up the mapping and **creates** (unseen), **updates**
(checksum changed), or **skips** (unchanged) the local row through `source.apply`, appending one
record-log line — then closes the run `succeeded` with the counts + next cursor. It is
**at-least-once + idempotent**: a per-record failure is logged (`ACTION_FAILED`) and does **not**
abort the run; a failure of the *pull itself* closes the run `failed` and **re-raises**, so the
outbox retries the whole job and the mapping ledger makes the replay a no-op. Both `SyncRun` and
`SyncMapping` writes flow through an audited `BaseService`; the record log rides the write unit.

### 4. Jobs + schedule, declared on the module

`SYNC_PULL` / `SYNC_PUSH` are typed `JobDefinition`s the handler resolves a source for and runs;
the module declares them (`ModuleSpec.jobs`), so mounting it registers them. `sync_pull_schedule`
/ `sync_push_schedule` build a typed `ScheduleDefinition` whose `payload_factory` carries the
entity type fresh each tick — an app drops it into its `ScheduleCatalog`.

### 5. A **library** capability (explicit mount) + read-only admin router

Like `identity`, `sync` declares a `terp.migrations` entry point (its own linear history /
`alembic_version_sync` table) but **no** `terp.capabilities` auto-discovery: a sync does nothing
until an app registers a `SyncSource`, so the app mounts the exported `module` explicitly and
calls `register_sync_source(...)` at composition time. The admin-only (`ADMIN`) router exposes
**reads only** — runs, per-record logs, and the mapping ledger — an operator's window into what
each reconcile did and why. All sync mutations happen through the jobs, never the router.

## Consequences

- An app adds a full, retrying, scheduled, audited sync by writing **one** `SyncSource` +
  registering it + mounting the module + declaring a schedule — no engine, no bespoke worker.
- in-process → outbox → broker and external-cron → APScheduler → Celery-beat swap underneath it
  with **no** change to the `SyncSource` or the schedule (they are the same typed constants).
- The example app is untouched (sync is not mounted, registers no source) and its escape-hatch
  budget stays `{}`; the frontend OpenAPI contract is unchanged (a library cap adds no route to
  the base profile).
- A job that dies mid-loop leaves a `running` run whose per-record work already committed; the
  next successful run supersedes its cursor. Reaping stale `running` runs is a follow-up.

## Enforcement (the ADR-0006 quadruple)

1. **Typed registry + safe default** — the `SyncSource` registry + the reconcile decisions keyed
   on the unique `SyncMapping` ledger; the safe default queue (in-process / outbox) and the
   external-trigger schedule need no engine.
2. **Fail-closed runtime** — `resolve_sync_source` rejects an unregistered type (`SyncError`);
   every local + bookkeeping write routes through an audited `BaseService`; the append-only log
   rides the audited write unit (the scope primitive stays `_internal`); a pull failure closes
   the run `failed` and re-raises for outbox retry; `push` fails closed unless the source
   implements it.
3. **Build-time** — the capability arch harness scans `sync` under its ratcheted
   `escape-hatch-budget.json` (`sync` added to `_BUDGETED_CAPS`, so it can never silently escape
   the harness); `tests/architecture/test_sync.py` holds the capability at **100% line coverage**
   (create/update/unchanged, per-record failure, pull failure + re-raise, cursor resume, push +
   its fail-closed default, the scheduler trigger, and the admin router); the migration
   conformance gate round-trips the `sync_mapping` / `sync_run` / `sync_record_log` tables and
   asserts no model drift.
4. **Budgeted escape hatch** — `escape-hatch-budget.json` ratchets the three governed markers of
   the append-only record log (`arch-allow-no-internal-imports` for the write-unit primitive,
   `arch-allow-mutations-emit-audit` ×2 for the base-of-stack append, `arch-allow-table-models-
   use-base-table` for the immutable log row) — the same posture the audit sink and webhooks
   delivery log already carry.

`terp.core` is unchanged, so the vendored mirror stays byte-exact and its 100% line coverage is
untouched; the sync capability itself is held to the same 100% gate.
