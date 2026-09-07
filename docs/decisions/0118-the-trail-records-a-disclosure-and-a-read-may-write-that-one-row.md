# 0118 — The trail records a disclosure, and a read may write that one row

- **Status:** Accepted
- **Date:** 2026-09-06
- **Relates:** [ADR 0007](0007-audit-auto-emit-and-the-audit-seam.md) (the audit seam and
  its auto-emit from the write chokepoint — this adds the verb that has no chokepoint),
  [ADR 0015](0015-runtime-write-guarded-session.md) (the write-guarded session this
  deliberately steps outside of),
  [ADR 0028](0028-adversarial-review-third-batch.md) §F2 (the read-only request scope, whose
  boundary this decision draws),
  [ADR 0038](0038-base-service-commit-ownership.md) (the chokepoint owns the commit — a
  disclosure owns its own instead),
  [ADR 0002](0002-control-plane-and-auditable-module-authority.md) (auditable module
  authority)

---

## Context

The audit trail could describe a write and nothing else. `AuditAction` was `created` /
`updated` / `deleted`, and `emit_audit` is called from the single `BaseService` write
chokepoint, which is what makes the trail free of module wiring: mutate through the
chokepoint and you are audited whether or not you remembered to be.

That design answers "who changed this row" completely and "who *saw* this row" not at all.
The gap is not hypothetical, and it is not small. An export endpoint that streams a payroll
file, a download of a stored document, a screen that reveals a supplier's bank details
behind a grant, a support tool that renders another tenant's record — each of these hands
guarded data to a person, and each left no trace whatsoever. Under most access-control
regimes the disclosure is the reportable event; the framework was recording the one thing
that is usually recoverable from the data itself and omitting the one thing that is not.

Adding a fourth verb is trivial. What made this worth an ADR is that **the framework is
built to prevent the write it requires**, in two independent layers, and both refusals are
correct in every other case:

1. The request session is a `WriteGuardedSession` (ADR 0015). It refuses `add` and `commit`
   outside `allow_session_writes()`, so a module cannot persist anything without going
   through the audited chokepoint.
2. `create_app` opens `read_only_request(True)` for every safe method (ADR 0028 §F2). During
   a `GET` the guard refuses a write *even inside* the chokepoint, because a request
   authorized only at the read tier must not mutate — a privilege-tier escape otherwise.

A disclosure happens during a `GET`. So the record that says "this data was read" is refused
by the guard whose job is to ensure a read changes nothing. The two are only in conflict if
you take "changes nothing" to include the trail, and the trail is not business state — it is
the evidence that the read occurred.

There is also no transaction to ride. Every other audit record is staged into the business
transaction that caused it and committed by the chokepoint, atomically, so a failed mutation
cannot leave a record claiming it happened. A read has no such unit of work, and nothing on
the read path ever commits.

## Decision

`terp.core.emit_disclosure` — the read counterpart of `emit_audit`, carrying the new
`AuditAction.DISCLOSED`.

**It takes no session and owns its own transaction.** It opens a session on the engine,
calls the active sink, and commits, inside `fresh_write_scope()` + `allow_session_writes()`.
`fresh_write_scope` is the primitive a background job already uses (ADR 0038) and it is
exactly right here for the same reason: this record is its own outermost unit of work at the
envelope's authority, not a participant in whatever the request is doing. It clears the
read-only flag — the load-bearing part, without which the write is refused — and resets the
depth counter, so the disclosure is genuinely outermost rather than appearing nested inside a
caller's unit that lives on a different session and could not commit it.

**It is called before the data is handed over, not after.** A sink that raises propagates,
the endpoint fails, and nothing is disclosed. This is the property the ordering buys, and it
is why the separate transaction matters rather than being an implementation detail: the
record is durable at the moment the call returns, so a request that discloses data and *then*
fails has still left the trail. Recording afterwards would invert the guarantee into "we will
try to remember what we already gave away".

**The verb needs no migration.** The `action` column is a bounded `AutoString(16)` with no
native enum and no CHECK constraint — a deliberate choice at the time, so that this low-layer
capability needs no higher-layer enum — and `disclosed` is nine characters. An existing
database stores the new verb the moment the code ships. A test pins the column bound against
the value, so this stops being true loudly rather than at the first INSERT.

**Emitting it stays deliberate.** There is no chokepoint to hang it on: only the endpoint
knows that what it is about to return is guarded rather than ordinary. Auto-emitting on every
read would bury the reportable events under millions of list requests and make the trail
useless for the purpose it was added for.

## Consequences

- The trail can express "who saw this", and an app can answer a disclosure question without
  reconstructing it from access logs that were never designed to be evidence.
- Exactly one write is permitted during a safe method, it is not business state, and it is
  named. The read-only guard is otherwise untouched — no route, service, or module gains any
  new ability to mutate during a `GET`.
- A disclosure costs a second connection and a commit. That is the price of the record
  outliving the request, and it falls only on the endpoints that opt in.
- A sink outage now fails a read endpoint that discloses. That is intended, and it is the
  fail-closed direction: refusing to hand over data we cannot account for.
- Because the call is deliberate, a missed call site is a silent gap. Coverage is a review
  question per endpoint, not something the framework can prove — the position ADR 0007
  deliberately avoided for writes, accepted here because the alternative is no trail at all.

## Alternatives considered and not taken

**Stage the record on the request session and let something commit it later.** Nothing does.
The read path has no commit, and the guard refuses one during a safe method — the two reasons
this needs its own transaction in the first place. Adding a read-path commit would mean
giving every `GET` a unit of work, a far larger change than the problem justifies, and it
re-opens the hole ADR 0028 §F2 closed.

**Relax the read-only guard so any write is allowed during a safe method.** One line, and it
deletes a real protection: the guard exists because a handler that mutates on a `GET` has
escaped its privilege tier. Trading that for one row is a bad trade. Opening the scope
around this single, framework-owned write keeps the guard intact for everything else.

**Use a plain `Session` and sidestep the guard entirely.** It would work, and it would be
quieter — which is the objection. A reviewer reading `Session(get_engine())` in the audit
module has no way to see that two guards were deliberately stepped past, or why. The explicit
scopes name what is being permitted, and keep row scoping in force for anything a future sink
might read.

**Auto-emit on reads from the chokepoint, the way writes work.** Attractive for symmetry and
wrong in substance: the framework cannot tell a payroll export from a dropdown lookup, and a
trail that records both records neither usefully. Deliberate emission keeps the signal.
