# 0015 - Runtime write-guarded session (the structural audited-write chokepoint)

- **Status:** Accepted
- **Date:** 2026-06-24
- **Context phase:** Phase 2 (base profile), continuing the adversarial-review
  follow-ups
- **Relates:** [ADR 0006](0006-cross-cutting-controls-and-opinionation-policy.md)
  (the two-layer discipline: a fail-closed runtime control **and** a build-time
  test), [ADR 0007](0007-audit-auto-emit-and-the-audit-seam.md) (the audited
  `BaseService` write chokepoint), [ADR 0014](0014-adversarial-review-hardening.md)
  (which strengthened the build-time rule and sequenced this runtime guard as the
  deeper fix). Findings: [docs/reviews/2026-06-24-adversarial-design-review.md](../internal/reviews/2026-06-24-adversarial-design-review.md)
  (C1 / C2).

---

## Context

The headline guarantee "**all persistence flows through one audited chokepoint**"
rested on a single build-time control, the `terp.arch` `mutations_emit_audit`
rule. The adversarial review (C2) showed that rule is a *heuristic*: it matches
session writes by a fixed set of variable names and verbs, so a write smuggled
under a renamed variable (`s.add(...)`), through `session.execute(update(...))`,
or from inside a capability package the harness did not scan, persisted a mutation
with **no audit record and no arch violation**. ADR 0014 broadened the rule
(bulk/flush verbs, DML via `execute`/`exec`, annotation-based receiver detection,
capability scanning) but a static rule can only ever approximate "this is a write
to the request session" — it cannot see every shape, and it is the *only* thing
standing between an agent and an unaudited write.

The missing half was a **runtime** control. The audited chokepoint is
`BaseService._save` / `_remove`; every legitimate write already goes through it
(`create` / `update` / `delete`, and a bespoke mutation re-uses `_save`). So the
request session can simply **refuse** to persist anything that is *not* inside
that chokepoint, structurally, regardless of how the write is spelled.

## Decision

`SessionDep` hands out a **write-guarded session**, and `BaseService` opens a
narrow dynamic scope around its persistence; a write outside that scope fails
closed at runtime.

1. **`WriteGuardedSession` (the runtime control).** A `sqlmodel.Session` subclass
   (in `terp.core._internal.session_guard`) whose mutating methods — `add`,
   `add_all`, `delete`, `merge`, `commit`, `bulk_save_objects`,
   `bulk_insert_mappings`, `bulk_update_mappings`, and a DML `execute` / `exec`
   (anything that is not a `SELECT`) — raise `UnauditedWriteError` unless they run
   inside `allow_session_writes()`. `get_session` (the `SessionDep` provider) now
   yields this guarded session, so **every** request session is guarded.

2. **`BaseService` owns the only write scope.** `_save` and `_remove` wrap their
   persistence (the `session.add` / `delete`, the in-transaction `emit_audit`, the
   `_after_write` hook, the `commit`) in `allow_session_writes()` — a `ContextVar`
   scope with token-based reset, so the audit sink's nested `session.add` and a
   nested `_save` (a service whose `_after_write` writes again) are correctly
   inside it. Outside that scope the session is read-only.

3. **The scope opener is unreachable from a module.** `allow_session_writes` lives
   under `terp.core._internal`, which the `no_internal_imports` arch rule forbids a
   module or capability from importing — so an agent cannot wrap its own raw write
   in the scope to wave past the guard. That rule is the **second layer** guarding
   the guard itself.

4. **Reads and `flush` stay free.** A `SELECT` through `exec` / `execute` runs
   anywhere. `flush` is deliberately **not** guarded: SQLAlchemy autoflush calls it
   during reads, and guarding it would make an incidental autoflush of a
   legitimately-dirty entity fail. This is safe because nothing a guarded session
   flushes is durable without the guarded `commit` (the request session is rolled
   back on close), and `add` / `delete` are already refused outside the scope, so
   no *new* or *deleted* row can be staged outside it.

5. **It is a programming error, not a client error.** `UnauditedWriteError` is a
   `RuntimeError` (not an `AppError`), so it surfaces as a generic 500 through the
   composition root's catch-all handler — a loud bug signal, never a handled,
   client-facing envelope.

The build-time `mutations_emit_audit` rule is **kept** as the second layer: it
still flags the common shapes at build time (a faster, more precise signal than a
runtime 500), while the runtime guard is now the structural primary control. This
preserves the ADR 0006 two-layer discipline with the layers correctly ordered —
the runtime control is fail-closed and complete, the build-time test is the
early-warning.

## Consequences

- The audited-write guarantee is now **structural**: a persistence that skips
  `BaseService` fails closed at runtime no matter what the session variable is
  named or which package it lives in — exactly the class of bypass (C1 / C2) the
  build-time rule could only approximate.
- Tests and other callers that construct a **bare** `Session(engine)` are
  unaffected (only `SessionDep` is guarded); the scope toggling is an inert
  `ContextVar` flip around their writes.
- **Known residual (documented, out of scope for a method guard):** a plain
  attribute mutation on an already-loaded entity (`row.title = x`) is not a session
  *method*, so if it is later flushed by an unrelated `_save`'s `commit` it rides
  that commit unaudited. Catching that needs change-tracking at commit time, a
  deeper control than session-method interception; it is tracked separately and is
  unchanged by this ADR. The common, agent-reachable bypass — explicit
  `session.add` / `commit` / `execute(DML)` — is now closed.
- **Engine-escape boundary (the F3 follow-up, ADR 0026).** The guard intercepts the
  request `Session`'s *methods*; the bound `Engine`/`Connection` the session exposes
  is a second surface. `session.connection()` is now guarded too, but a fresh
  connection obtained from `session.get_bind().connect()` is a separate transaction
  this method guard cannot reach. That residual is closed at *build* time by the
  `no_raw_connection_access` rule (a module may not call `get_bind` / `connection`;
  the `get_bind().connect()` escape is caught at the `get_bind` call); so this ADR's
  "every shape … regardless of how the session variable is
  named" claim is precise for the **session** surface, with the engine surface
  covered by the paired build rule rather than the runtime method guard.
- 297 tests, 100% framework line coverage.
- **Still open (sequenced as their own decisions):** the `Permission`-in-`Policy`
  guard (H1), the non-overridable `base_query` scope predicate (H2), the
  `response_model`-not-a-table rule (H3), and first-class
  `create_app(..., middleware=/tenant_resolver=)` plus tenant-aware login (H7/H8).
