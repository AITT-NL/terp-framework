# 0007 - Audit auto-emit: the AuditPolicy registry + the core audit seam

- **Status:** Accepted
- **Date:** 2026-06-24
- **Context phase:** Phase D (the highest-value Tier-A gap per ADR 0006)
- **Supersedes/relates:** [docs/IMPLEMENTATION_PLAN.md](../internal/IMPLEMENTATION_PLAN.md) §5
  (Phase D) + §10, [ADR 0006](0006-cross-cutting-controls-and-opinionation-policy.md)
  (Tier A/B/C + the "quadruple"), [ADR 0002](0002-control-plane-and-auditable-module-authority.md)
  §3.2 (two kinds of "off")

---

## Context

ADR 0006 classified an **audit log of mutations** as the leading **Tier-A**
("mandatory") gap: no business app should silently mutate state without a trail of
*who did what, when*. Prior practice proved the pattern (an append-only
log written next to each write, with central redaction and a retention worker), but
its trail was opt-in per route — a router had to remember to call
`record_audit_event`, and a build-time rule policed that every mutating route did.
Terp's thesis is stronger: make the trail **unbypassable** and **wiring-free** by
emitting it from the one place every mutation already flows through.

## Decision

Ship audit as the full **quadruple** ADR 0006 requires, honoring the layering rule
that `terp.core` must not depend on a capability.

1. **A typed control-plane registry with a safe default — `AuditPolicy`.** Lives in
   `terp.core` on `ControlPlane.audit` (like `SecurityConfig`). The default audits
   **every** mutation; it centralizes redaction (`redact_keys`, masking
   credential-bearing payload keys) and carries a `retention_days` knob (the
   window; pruning is a later worker). It is never silently absent — turning it off
   is the explicit, justified `AuditPolicy.disabled(reason=...)`.

2. **A fail-closed runtime control — auto-emit from the single chokepoint.**
   `BaseService.create` / `update` / `delete` route every write through one
   `_save` / `_remove` primitive that calls `emit_audit(...)` **inside the write's
   transaction**, so the audit row commits atomically with the business change and
   a sink that raises aborts the mutation rather than losing the trail. A module
   gets a complete trail with **zero** code. A bespoke service mutation (e.g. the
   reference `tasks` soft-delete) re-uses `_save`, so it is audited too.

3. **A build-time test — the `terp.arch` `mutations_emit_audit` rule.** It forbids a
   module from writing to the session directly (`session.add` / `delete` / `merge` /
   `commit`); persistence must go through the audited `BaseService` chokepoint. The
   rule is registered in `_ALL_RULES`, carries a matching `test_mutations_emit_audit`,
   and the harness self-completeness meta-test enforces the pairing.

4. **A budgeted, explicit escape hatch.** Turning the control off is
   `AuditPolicy.disabled(reason=...)`; a module that genuinely must bypass the
   chokepoint uses a justified `# arch-allow-mutations-emit-audit: <reason>` marker,
   which the escape-hatch budget ratchets. The example app needs **neither** — its
   budget stays `{}`.

### Layering: a core seam + a capability sink

`terp.core` defines only the **seam** — the typed `AuditAction` / `AuditRecord`, the
`AuditPolicy` registry, an `audit_actor_ctx` context var, and `emit_audit`, whose
**default sink only logs** a structured, redacted line (no persistence). This
mirrors the existing seams: `get_principal` (auth) and `base_query` (tenancy) ship
inert defaults that a capability fills.

The **durable** half is the opt-in `terp-cap-audit` capability: an append-only
`AuditEvent` table (composing `UUIDPrimaryKeyMixin`, not `BaseTable` — rows never
change, so no `updated_at` / `version`), the `persist_audit` sink, and a
self-registering, **admin-only** router to read the trail. The composition root
wires the sink in one line — `create_app(..., audit_sink=persist_audit)` — after
which every module is audited; the actor is resolved through the same
`get_principal` seam the guard uses (an async dependency `create_app` mounts on
every router), so the trail records *who* acted with no module wiring.

### Event bus split out

Phase D in the plan bundled an event bus with audit. We **split** it: audit-first
keeps the increment small and green. The event bus (and `ModuleSpec.emits` /
`subscribes` becoming typed catalog references) remains future work; audit does not
depend on it.

## Consequences

- Every `BaseService` mutation in every module/capability now emits an audit
  record. With no `terp-cap-audit` installed the record is logged (defense in
  depth); with it installed the record is an append-only row committed atomically
  with the business write.
- The audit sink is a process-global seam (the service layer has no app handle), so
  test isolation is enforced by a repo-root autouse fixture that resets the runtime
  to the log-only default after each test. `create_app` reconfigures it per build.
- New cross-cutting controls continue to land by tier. The next Tier-A-adjacent
  follow-ups remain the Tier-B **password policy** and the **`__tablename__`
  required + name-pattern** rule; the event bus is the next Phase-D subsystem.
- `AuditPolicy.retention_days` is declared but not yet enforced (no pruning worker);
  recorded as a tracked gap, not a silent omission.

## Decision

Status: **Accepted** — audit auto-emit ships as the ADR 0006 quadruple (AuditPolicy
registry + fail-closed auto-emit + the `mutations_emit_audit` build-time rule +
budgeted opt-out), split from the event bus, with the core seam / `terp-cap-audit`
sink layering. Gate: **200 passed, 100% line coverage**; the example app dogfoods
the trail clean with an escape-hatch budget of `{}`.
