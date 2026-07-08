# 0008 - The event bus: a typed EventCatalog + NO-DRIFT emit + in-process dispatch

- **Status:** Accepted
- **Date:** 2026-06-24
- **Context phase:** Phase D (the open event-bus subsystem, deferred by ADR 0007)
- **Supersedes/relates:** [docs/IMPLEMENTATION_PLAN.md](../internal/IMPLEMENTATION_PLAN.md) §5
  (Phase D) + §3.2 (two kinds of "off") + §3.6 (centralization enforcement) + §10
  (Tier A/B/C), [ADR 0007](0007-audit-auto-emit-and-the-audit-seam.md) (which split
  the event bus out of audit), [ADR 0002](0002-control-plane-and-auditable-module-authority.md)

---

## Context

Phase D bundled an event bus with audit. ADR 0007 deliberately **split them**:
audit shipped first (a mandatory Tier-A control), and the event bus was left as the
open Phase-D subsystem. This ADR ships it.

The event bus is a **different kind of concern** from audit, and the distinction is
the whole point (design §3.2 / §10). Audit is **Tier-A mandatory**: it may never be
silently absent, so its registry is required and turning it off is an explicit,
budgeted act. The event bus is an **optional product feature**: an app that declares
no events simply has none — no ceremony, no "always on" default. What the framework
guarantees instead is **no drift**: every event a module emits or subscribes to is a
registered, typed object, never a bare string. Prior practice proved the
pattern (a typed `EventDefinition` catalog, an `emit()` that only accepts catalog
constants, a handler registry, and — separately — a durable transactional outbox
with a worker); Terp re-authors the catalog + typed emit + in-process dispatch
company-agnostically and **defers the durable outbox**.

## Decision

Ship the event bus honoring the layering rule (`terp.core` must not depend on a
capability) and the two-kinds-of-"off" rule (a product feature may be silently
absent; the guarantee is no-drift, not "always on").

1. **A typed control-plane registry — `EventCatalog`.** Lives in `terp.core` on
   `ControlPlane.events` (like `SecurityConfig` / `AuditPolicy`), but its default is
   **empty** — the event bus is *inactive* until events are declared. An
   `EventDefinition` is a typed contract: a dotted `name`, a `payload_schema` (a
   model validated on emit), and an `EventVisibility` (`PUBLIC` / `INTERNAL` /
   `RESTRICTED`). The catalog rejects duplicate names.

2. **A fail-closed runtime control — typed `emit()` that rejects unknown events and
   shadows.** `terp.core.emit(session, *, event, payload=None)` accepts **only** an
   `EventDefinition`, resolves the **canonical** entry from the active catalog, and
   raises `EventError` if the name is unregistered **or** the passed definition is a
   same-name *shadow* (a look-alike with a different payload schema or visibility) —
   matching by value, not just by name, so the catalog stays the one source of
   truth. It then validates the payload against the **canonical** definition's
   schema, builds a typed `EventEnvelope` (capturing the request id) from the
   canonical visibility, and hands it to the active **dispatcher**. The dispatcher is
   a core **seam** whose default is a **no-op** — an app that declares a catalog but
   installs no event-bus capability still validates every emit; the event simply
   goes nowhere. This mirrors the audit seam (`emit_audit`'s default sink only logs).

3. **A build-time test — the `terp.arch` `events_reference_catalog` rule.** It
   forbids a bare string (or an inline `EventDefinition(...)`) wherever an event is
   named: the `event=` of `emit(...)`, the argument of a `subscribe(...)` decorator,
   and the `emits` / `subscribes` lists of a `ModuleSpec(...)`. Registered in
   `_ALL_RULES`, paired with `test_events_reference_catalog`, and enforced by the
   harness self-completeness meta-test.

4. **Boot validation of the manifest — `emits` / `subscribes` become typed.**
   `ModuleSpec.events` (an inert bare-string field) is replaced by typed
   `emits: Sequence[EventDefinition]` and `subscribes: Sequence[EventDefinition]`.
   `create_app` validates every reference against the catalog (like `Policy` refs)
   and fails the boot on an undeclared event — the static half of the no-drift
   guarantee.

There is **no budgeted escape hatch** for "turn the event bus off", because — unlike
audit — there is nothing to force on: an app with no events is the silent, valid
default. The only governed control is no-drift, enforced at boot, at runtime, and at
build time.

### Layering: a core seam + a capability dispatcher

`terp.core` defines only the **seam** — `EventDefinition` / `EventCatalog` /
`EventEnvelope`, the `emit` chokepoint, and a dispatcher whose default delivers
nowhere. The **in-process** half is the opt-in `terp-cap-eventbus` capability: a
handler registry (`subscribe`, keyed by a typed catalog event — never a string) and
`dispatch_in_process`, which fans an envelope out to every subscribed handler
synchronously in the caller's transaction. It is a **library** capability — no entry
point, no router, no tables — installed in one line:
`create_app(..., event_dispatcher=dispatch_in_process)`.

### The durable outbox is split out (deferred)

A conventional bus persisted a `DomainEvent` + per-handler dispatch
rows in the producer's transaction and drained them with a leased, retrying worker
(a transactional outbox with a dead-letter queue). That is a substantial subsystem.
We **ship the catalog + typed emit + in-process dispatch first** and defer the
durable outbox + worker, keeping the increment small and green — exactly as ADR 0007
split the bus out of audit. The dispatcher seam makes the outbox a later, drop-in
replacement for `dispatch_in_process`: a durable dispatcher writes rows on the
`session` it already receives, with **no change to any `emit` call site**.

## Consequences

- The event bus is **off by default and costs nothing**: `ControlPlane.events` is
  empty, the dispatcher is a no-op, and no module is forced to emit or subscribe.
  Declaring a catalog turns it on; every reference is then validated three ways.
- Emission is **explicit**, not automatic: a service calls `emit()` next to its
  write when it has something to announce. Audit (Tier-A) auto-emits from the
  `BaseService` chokepoint; events (a product feature) do not — they are not baked
  into the write path, so the bus stays opt-in.
- The dispatcher/catalog are process-global seams (the service layer has no app
  handle), so a repo-root autouse fixture resets the event runtime (empty catalog +
  no-op dispatcher) after each test, alongside the audit reset. `create_app`
  reconfigures it per build.
- In-process handlers run **synchronously in the producer's transaction**; a handler
  that raises propagates (fail-closed). The producer folds `emit()` into the write
  via a new `BaseService._after_write` hook — it runs after the row + its audit
  record are staged but **before** the commit, so the event (and a future durable
  dispatcher's outbox row) rides the same atomic unit of work as the row, and a
  failing handler rolls the write back rather than committing without it. The
  reference `notes` service overrides that hook instead of `create`. Cross-process
  delivery, retries, and a dead-letter queue arrive with the deferred durable outbox.
- The realtime/websocket subsystem (Phase E) is designed to be **driven by this
  bus** (a registered topic subscribes to catalog events); it remains future work.

## Decision

Status: **Accepted** — the event bus ships as a typed `EventCatalog` registry +
a fail-closed `emit()` that accepts only catalog events + an in-process handler
registry, with `ModuleSpec.emits` / `subscribes` promoted to typed catalog
references validated at boot, and the `events_reference_catalog` build-time rule.
Layering is honoured (core seam with a no-op default dispatcher; the in-process
dispatcher in `terp-cap-eventbus`), the durable outbox is split out for a later
increment, and the example app dogfoods the bus clean with an escape-hatch budget
of `{}`. Gate: **230 passed, 100% line coverage**.
