# 0038 - BaseService commit-ownership: the chokepoint owns one re-entrant commit

- **Status:** Accepted
- **Date:** 2026-06-29
- **Context phase:** Phase 2 (base profile), closing the last open design decision
  recorded in [ADR 0001](0001-terp-namespace-and-kernel-scope.md) (Decision 9:
  "`BaseService` commit-ownership remains an open design decision")
- **Relates:** [ADR 0007](0007-audit-auto-emit-and-the-audit-seam.md) (the audited
  `_save` / `_remove` chokepoint emits inside the write's transaction),
  [ADR 0015](0015-runtime-write-guarded-session.md) (the `WriteGuardedSession` that
  refuses persistence outside that chokepoint), [ADR 0006](0006-cross-cutting-controls-and-opinionation-policy.md)
  (the Tier-A quadruple). Calibrates [STATUS](../internal/STATUS.md) deferred backlog
  ("`BaseService` commit-ownership — design decision pending").

---

## Context

Audit auto-emit (ADR 0007) committed *inside* each write: `BaseService._save` and
`_remove` call `session.commit()` directly, so the row, its audit record, and the
`_after_write` side effect land in one transaction. The write-guarded session
(ADR 0015) then made the request session refuse any `commit` outside that scope.
Both pin the commit at the **service chokepoint** — but neither decided what
happens when a write **re-enters** the chokepoint. An `_after_write` hook may call
`self._save` to persist a derived row, and a bespoke method may call `_save`
twice; each inner `_save` committed again, so the outer write was already durable
before the outer commit ran. That is the open ambiguity STATUS recorded: a write
graph could land as **two commits** (the inner one durable even if the outer body
later raised), so "every write is one atomic, audited unit" was not guaranteed for
nested writes. The two candidate owners were the **service chokepoint** (status
quo) and the **request seam** (commit once at `SessionDep` teardown).

## Decision

**The service chokepoint owns the commit, and the write scope is re-entrant: the
outermost `_save` / `_remove` commits exactly once; a nested write joins the same
unit of work.** The request seam stays read-only — `SessionDep` never commits.

### 1. One re-entrant unit of work (runtime)

- `enter_write_unit()` (in `terp.core._internal.session_guard`) opens
  `allow_session_writes` **and** bumps a depth counter, yielding `True` only for the
  outermost write. `_save` / `_remove` stage the row + emit the audit record + run
  `_after_write`, then: the **outermost** write commits (mapping `IntegrityError` →
  409, refreshing); a **nested** write `flush`es and returns, deferring the single
  commit to the outermost. So a derived `self._save` from `_after_write` lands in the
  same transaction as its trigger — no double commit, no half-committed graph.
- The depth lives in its own `ContextVar`, separate from the allow flag, so
  `forbid_session_writes` (re-armed around `_after_write`, ADR 0026 F5) never disturbs
  it. Token-based reset unwinds the whole unit on any exception (one rollback).

### 2. The guarantee is unchanged, only completed

`UnauditedWriteError` and the audit emit are **not** weakened: a write outside the
chokepoint still fails closed, and every staged row still emits its record in the
same transaction. The only change is that re-entry now *joins* instead of
*re-commits*. Reads, `flush`, and a bare `Session(engine)` (tests, CLI) are
untouched.

### 3. Long-term transaction shape

SQLAlchemy's clean unit-of-work guidance is to frame a transaction once, with the
outer scope committing on success and rolling back on exception; `flush()` is only
the in-transaction staging point, and after a failed flush the application must call
`rollback()` before continuing with that `Session`. Terp follows that shape, but its
outer scope is deliberately the **audited service chokepoint** rather than raw request
teardown: `_save` / `_remove` are where audit emit, actor/owner traits, object authz,
409 mapping, and the write guard meet.

The long-term clean abstraction is therefore a first-class framework **write unit**
(a small internal context / service-orchestrator primitive) that frames
`begin/commit/rollback`, exposes "outermost vs joined" explicitly, and lets several
sanctioned service writes compose without nested commits. This ADR is the minimal
version of that primitive (`enter_write_unit`). If Terp later adds command handlers /
workflow services that intentionally coordinate several `BaseService` writes, they
should open that write unit explicitly and let leaf services join it. We should not
move commit ownership to `SessionDep` teardown: it is too far from the audited row
write, makes errors harder to map, and invites unaudited dirty state to ride the
request's final commit.

### 4. Quadruple (ADR 0006)

- **Registry + safe default:** the chokepoint owns the commit; nesting is automatic.
- **Fail-closed runtime:** the re-entrant scope + `UnauditedWriteError` (a stray
  `commit` outside it is still a 500).
- **Build-time test:** the `terp.arch` `mutations_emit_audit` rule still forbids a
  module's own `session.commit`; the kernel suite adds the single-commit-per-unit
  invariant for nested `_save` / `_remove`.
- **Escape hatch:** none needed; the example budget stays `{}`.

## Consequences

- Every write — however nested — is one audited, atomic transaction; a failing
  outer commit rolls back the derived rows too. The double-commit / partial-txn
  footgun is gone, self-contained to `terp.core` (no app/cap churn).
- Closes the last ADR 0001 Decision-9 deferral. Gate: changed core files at 100%
  line coverage; vendored mirror refreshed (byte-match drift gate).

## Alternatives considered

- **Request seam owns the commit (`SessionDep` commits once on teardown).** Rejected:
  it decouples the commit from the audit-and-business unit (ADR 0007's atomicity),
  breaks every bare-`Session` caller (tests, CLI, migrations) that expects `create`
  to persist, and an exception path would have to choose commit-vs-rollback far from
  the write — broad blast radius for no extra safety. The chokepoint is already where
  audit + actor-stamp + 409 mapping live.
- **Forbid nested `_save` entirely.** Rejected: `_after_write` deriving a row is a
  legitimate, audited pattern; re-entrancy keeps it one unit rather than banning it.
