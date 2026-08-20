# ADR 0095 — Expiring, fenced custody of work: the lease seam and its reaper

- Status: Accepted
- Date: 2026-08-20
- Relates to: ADR 0043 (the jobs seam — the port whose *consumers* kept needing this),
  ADR 0045 (the durable outbox, whose batch claim is the reviewed exception this rule
  carves out), ADR 0038 (the re-entrant `enter_write_unit` chokepoint that makes
  recovery-plus-forfeit one transaction), ADR 0006 (the port + safe-default + fail-closed
  boot-guard quadruple this seam follows in shape and deliberately breaks in one place),
  ADR 0017 / ADR 0029 (the predicate/trait registries this reaper registry mirrors),
  ADR 0040 (the `is_durable_*` boot-marker shape), ADR 0088 (service accounts — the
  machine identity a foreign worker already has), ADR 0080 (the Terp Standard entry this
  ships)
- Rejects, with reasons: a `LeasedMixin` trait on the domain table; a pluggable
  `LeaseStore` with an in-process default; and a "lease a job over HTTP to a foreign
  worker" capability (§Alternatives)

## Context

Two friction reports arrived from building queue-shaped work on Terp, and they turned out
to be one missing primitive read from two sides.

**A row a crashed worker took stays taken.** A worker flips a request to `claimed` and
starts. It is killed — OOM, a rescheduled pod, a lost connection. Nothing in the schema
records *who* took the row or *until when*, so nothing can distinguish "still working"
from "died three hours ago", and the only recovery is a hand-written `UPDATE` by someone
with database access. The reporting app had already reached the only conclusion available
to it: leave the row `claimed` forever, because that is at least *honest*, and put a
staleness window in the service so one dead worker does not take a connection out of
service permanently. That is a good answer to a missing primitive. It is not a substitute
for one.

**Nothing enforces "at most one active run".** The same absence, from the other side: a
pipeline that must have one active run, a source that must not be reconciled twice
concurrently. Exclusivity *while a holder is alive* is expressible with existing
primitives (a partial unique index, an optimistic-concurrency claim). What is not is
exclusivity **with an expiry** — and without the expiry, the mutex has the first problem.

The decisive evidence was not either report. It was `terp-cap-sync`, whose own service
docstring had been carrying this since it shipped:

> *A job that dies mid-loop leaves a `running` run whose work already committed
> per-record; the next successful run supersedes its cursor — reaping stale runs is a
> follow-up.*

Two independent occurrences, one of them in the framework's own flagship consumer
capability, is the bar for promoting a pattern to a primitive.

`terp-cap-outbox` already has *a* lease — `locked_by` + `locked_until`, claimed by an
atomic UPDATE, reclaimed once the lock lapses. It is not a reusable primitive, and it is
also narrower than it looks: `locked_until` is set once at claim time and **never
renewed** (the worker's own guidance is to set the lease above the longest expected job),
so the framework had fixed-duration batch locks over one private table and nothing else.

## Decision

### 1. What a lease is: a resource, a holder, an expiry, and a fence

`terp.core.leases` defines the vocabulary. A `LeaseResource` is an opaque
`(kind, key)` pair — `LeaseResource.for_row(row)` for the row-custody case,
`LeaseResource("pipeline", str(pk))` for a mutex on something that is not a row at all. A
`Lease` is the immutable grant: resource, holder, `expires_at`, and `epoch`.

The `epoch` is the part that is easy to leave out and expensive to omit. Expiry alone
establishes that a holder *may* have died; it does nothing about a holder that merely
**paused** — a stalled process, a long GC, a suspended container — and wakes after its own
deadline to finish work a successor has already taken over. Every fenced statement carries
`AND epoch = :epoch`, and only a *grant* increments it (a renewal does not), so a
superseded holder's renew, release and forfeit all match zero rows. It is a separate
column from the OCC `version` deliberately: a lease must survive its holder writing to the
*business* row, and a token bumped by any unrelated update would invalidate a live lease
and strand the work it protects.

### 2. The store writes on the caller's session

`acquire` / `renew` / `release` / `expired` / `forfeit` / `purge` all take a `Session`,
because a lease is only correct if taking it is atomic with the state change it guards: a
claim that commits while the row change rolls back strands the resource just as badly as
the reverse. In practice a domain takes the lease from its service's `_after_write` hook,
so the claim joins the write unit `_save` opened. That ordering pays off twice: a resource
somebody else holds raises `LeaseHeldError` *inside* the write, so the row never reaches
`claimed` at all — no compensating update, no window where the two disagree.

### 3. There is deliberately **no** default store

This is the one place the seam breaks ADR 0006's quadruple, and the break is the point.
Every other store seam here (idempotency, throttle, cache) ships a safe in-process default
because degrading it costs a re-execution or a cache miss. Degrading a lease costs *two
workers running the same work at once* — the exact thing the lease exists to prevent — so
a per-process default would not weaken this seam, it would silently fail to deliver it.
Worse, it cannot deliver the headline feature at all: the in-memory state dies with the
very process whose crash the lease exists to survive, so there is nothing left to reap.

So `configure_leases(None)` is the default, `acquire_lease` fails closed with `LeaseError`
naming the missing wiring, and an app that wants leases *names its store*.
`InMemoryLeaseStore` ships as a test double and single-process convenience and is
deliberately **unmarked**, so `create_app(require_durable_leases=True)` refuses it — and
refuses `None` too, because a promise of exclusivity backed by no store at all is the
emptiest of the three.

### 4. `terp-cap-leases` and the `resource_lease` table

A new opt-in **library** capability (no `terp.capabilities` entry point — leasing does
nothing until an app wires the store) owns one `resource_lease` row per leasable resource:
`resource_kind`, `resource_key`, `holder`, `epoch`, `expires_at`, `acquired_at`,
`touched_at`, `created_at`, unique on `(resource_kind, resource_key)`. Like
`OutboxMessage` it composes `UUIDPrimaryKeyMixin` rather than `BaseTable`, for the reason
in §1. It ships an independent, linear Alembic history discovered through the
`terp.migrations` group (ADR 0027).

Four single atomic conditional statements carry the contract, so correctness never depends
on isolation level: **acquire** (`… WHERE epoch = :epoch AND (holder IS NULL OR
expires_at <= :now)`, inserting inside a SAVEPOINT on first use so a raced insert loses on
the unique constraint without poisoning the caller's transaction), **renew** (the fence
plus `expires_at > :now`, so a lapsed lease is never resurrected), **release** (the fence
*without* the expiry condition, so finishing late while nobody took over still hands the
resource back), and **forfeit** (the fence plus `expires_at <= :now`, so the reaper cannot
steal a live lease).

Two details keep the store honest about other people's transactions: every read selects
**columns, not the ORM entity**, so a lease row never enters the caller's identity map for
a conditional UPDATE to leave stale; and every DML runs with `synchronize_session=False`,
because the caller's session is theirs. `touched_at` plus `purge` keeps the table
self-limiting — a row-shaped resource would otherwise grow it once per row ever processed.
`SKIP LOCKED` is a constructor flag the deployment sets, not something the capability
reaches for the connection to discover; leaving it off is a contention choice, never a
correctness one.

### 5. The reaper: the half only the domain can write

An expired lease frees a *resource*. It does not free the *work* — and no generic
mechanism can know whether the right recovery is "queue it again", "close it failed" or
"leave it for a human". So a domain registers one `LeaseReaper` per resource kind
(`register_lease_reaper`, a capability registration like a scope predicate), and
`reap_expired_leases` scans a bounded batch of lapsed leases and, for each, runs the
recovery **and** forfeits the lease in a single transaction. That atomicity is what ADR
0038's re-entrancy is for: the domain's own audited `_save` nests into the reaper's write
unit, so recovery lands in the audit trail like any other mutation, and the cycle can
neither re-run a completed recovery forever nor lose the record that work needs picking
up.

Three outcomes, all normal: **recovered** (a reaper ran), **released** (no reaper for this
kind — the correct shape for a pure mutex, where expiry *was* the whole recovery, and the
lease is still forfeited or the scan would return it forever), and **failed** (the reaper
raised; the lease is left lapsed on purpose so the next cycle retries, and one domain's
bad recovery never aborts the cycle for the others). Reaping is at-least-once, so a
registered reaper must be idempotent.

The cycle ships as a declared `LEASE_REAP` job with a `lease_reap_schedule` helper, so it
runs through whatever an app already operates — APScheduler, Celery beat, a `CronJob`
calling `terp jobs run leases.reap` — with no new daemon. A reaper that only exists as a
CLI command is a reaper somebody has to remember to schedule, and "nothing reaped the
stale claim" looks exactly like "the work is still coming".

### 6. Visible, and actionable, to an operator

The capability mounts an admin read router (`GET /`, `GET /expired`, `POST /reap`) and the
CLI ships `terp leases list [--expired]` / `terp leases reap`. `list` names the holder and
the deadline — the distinction a bare `claimed` column cannot make — and calls out, *per
kind on the page*, any kind with no registered recovery, because "nothing reaped it" and
"nobody declared a recovery for it" look identical on the rows alone and the second is the
mistake an author actually makes. `reap` runs the same bounded, fenced cycle the job runs,
so pressing it during an incident does exactly what the schedule would have done.

There is deliberately **no** force-release, in the router or the CLI. Taking a live lease
away from a holder that may still be running is the split brain the fence exists to
prevent, and an endpoint or command for it would be a permanent invitation to cause one.
Both surfaces touch only already-lapsed leases; waiting out the expiry is what the expiry
is for.

### 7. `terp-cap-sync` is the first consumer, and the proof

The sync capability takes a lease on `(tenant_scope, entity_type)` for the length of a
reconcile — on the *source*, not the run row, because what must not overlap is the source
and because a lease on a row that does not exist yet cannot serialise the decision to
create it. It heartbeats from inside the record loop (writing only past the lease's
half-life, and raising `LeaseLostError` if it was taken over), releases in a `finally`, and
registers a reaper that closes an abandoned `running` run `failed` with the reason on the
row.

That is the acceptance test for this ADR: the deferred sentence in §Context is deleted, not
reworded. Leasing stays **optional** in sync — an app that wired no store reconciles
exactly as before — so adopting the capability is a decision about operational guarantees
and never a migration.

### 8. The Terp Standard entry

`backend/no_manual_lease_columns` refuses a table model that declares its own lease
bookkeeping (`locked_by` / `locked_until` / `leased_until` / `lease_expires_at` /
`heartbeat_at` / `claim_expires_at` and their spellings), with `terp guide leases` as the
recipe. `layer` is `static-portable`; `runtime.applicability` is `not-applicable`, and the
rationale records why rather than waving at it: column presence *is* observable at runtime
but not **attributable**, because one shared model registry holds both the app's tables and
the framework's own delivery table, which legitimately declares exactly these columns — the
same non-attribution as the import-form egress and background-runtime rules. The outbox
carries the governed, budgeted `# arch-allow-no-manual-lease-columns` markers with that
reason on the line.

## Alternatives considered

**A `LeasedMixin` trait, with the lease columns on the domain table.** This is what the
first friction report literally asked for ("a domain-row lease"), and it loses on three
counts. It needs a migration per leasing table, so adopting the primitive is a schema
change instead of a wiring change. Its heartbeat writes to *business* tables, which either
floods the audit trail or needs a documented exemption from it. And it cannot express the
second half of the ask at all: "at most one active run per pipeline" is a mutex on
something that is not a row, and a row-shaped trait has nowhere to put it. One table
keyed on an opaque `(kind, key)` serves both, needs no per-consumer migration, keeps
heartbeats off business tables, and makes reaping one indexed scan regardless of how many
domains lease.

**A pluggable `LeaseStore` with an in-process default**, matching every other store seam.
Rejected in §3: the default would be unsafe in a way the others are not, and it would fail
to deliver the feature rather than merely weaken it.

**A capability for "lease a job over HTTP to a foreign worker."** The second friction
report's proposed fix, and the diagnosis behind it is correct: the only consumer of the job
queue is `terp jobs worker`, an in-process Terp process, `run_job` is `_internal` by
design, and there is no HTTP claim/finish surface — which is why an app whose engine may
not import `app` code had to hand-roll a domain queue with claim/finish routes. We are
declining the artifact and shipping the primitive underneath it, for three reasons.

The authn half already exists: service accounts (ADR 0088) give a machine subject a
credential that resolves to the same `Principal` through the same guard, with an expiry and
a last-used stamp. The remaining gap is not authentication.

The jobs seam cannot be exposed as-is. A `JobEnvelope` names a typed Python function in
`active_job_catalog`, dispatched by `run_job` with actor/tenant binding; a non-Terp worker
cannot execute that. "Lease a job over HTTP" is therefore not a new transport over the
existing queue but a new *class* of work — remote-executed jobs, a serializable
result-report contract, and a story for keeping every resulting write behind the audited
chokepoint. That is an ADR-sized change to the async design, not an adapter, and it
deserves its own decision rather than arriving as a side effect of this one.

And the parts that were genuinely hard in the hand-rolled version were design calls, not
code a capability could have handed over: one grant covering claim *and* finish (a
principal that could take work but not close it would strand everything it touched), no
general update route, exclusivity through the platform's own concurrency column. What was
missing was the expiry — which this ADR supplies, and which removes the "stays `claimed`
forever, recoverable only by a hand-written `UPDATE`" failure mode that motivated the
request. If the foreign-worker queue shape deserves to be portable, it belongs in the
Standard as a documented shape before it belongs in the framework as a package.

## Consequences

- An app adopting leases wires one store and gets exclusivity, heartbeats, fencing,
  recovery, an operator view and a CLI. An app that does not is unaffected: the seam stays
  unconfigured and nothing in `terp.core` changes behaviour.
- `terp-cap-sync` no longer strands a `running` run, and no longer lets two reconciles of
  one source overlap. Its deferred follow-up is closed.
- A new refusal for existing apps: a table declaring hand-rolled lease columns now fails
  the gate. The remediation is a wiring change plus a reaper, and the governed
  `# arch-allow-no-manual-lease-columns` marker exists for a genuine batch-claim exception
  like the outbox's.
- Still open, deliberately: reaping is per-kind and cadence-driven rather than
  event-driven (an expiry does not notify anything), and remote-executed jobs for a foreign
  worker remain unbuilt, per §Alternatives.

## Release sequencing (this lands across two repos, in order)

`no_manual_lease_columns` ships its Terp Standard entry in **terp-spec 0.25.0** — a new
rule bumps the minor, and 0.24.0 was already published, so the entry could not be added to
it without two artifacts claiming one spec version (ADR 0081). The spec is consumed as a
package, never a repo path (ADR 0082), so until 0.25.0 is on PyPI + npm this repo is still
pinned to 0.24.0 and `test_spec_catalog` fails with exactly the right complaint: the
harness registers a rule the pinned catalog does not carry.

The order is therefore: publish terp-spec 0.25.0, then bump all three pins here together —
`terp-spec==0.25.0` (`pyproject.toml` dev group, plus `uv.lock`), `@terpjs/spec` in
`packages/frontend/eslint-boundaries/package.json`, and `SPEC_VERSION` in
`packages/backend/arch/src/terp/arch/__init__.py` (held equal to the pin by
`test_check_json.py`). Nothing else in this ADR depends on that bump; the seam, the
capability, the reaper and the sync consumer are all self-contained.
