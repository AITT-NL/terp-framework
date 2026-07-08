# 0009 - Authoring model & the opinionation boundary (declarative-by-default)

- **Status:** Accepted
- **Date:** 2026-06-24
- **Context phase:** post-Phase-D (event bus), opening the authoring-ergonomics track
- **Relates:** [docs/IMPLEMENTATION_PLAN.md](../internal/IMPLEMENTATION_PLAN.md) §10 (Tier A/B/C
  + Levels 0–2), [ADR 0006](0006-cross-cutting-controls-and-opinionation-policy.md),
  [ADR 0008](0008-event-bus-catalog-and-typed-emit.md)

---

## Context

Terp's purpose is to let non-technical owners (working through coding agents) and
the 60–70% of "ordinary" apps ship backend modules **without writing the hard
cross-cutting parts**, while the other 30–40% can still use the framework by
**configuring** non-default behaviour — never by forking a cross-cutting concern.

Two forces pull against each other, and conflating them has been a latent risk:

- **Target A — zero *drift* in cross-cutting concerns.** Auth, audit, events,
  errors, DB access, soft-delete policy, pagination, input caps: declared once in
  the control plane, referenced by modules, enforced fail-closed at boot *and* by
  the build-time harness. Pushing this **to the extreme is correct** — it is the
  differentiator.
- **Target B — "no *unexpected code* in a module at all."** Modules become
  fill-in-the-blanks forms with zero imperative logic. **Pursued to the extreme this
  is the low-code trap**: ~70% trivial, the last ~30% (genuine business logic)
  becomes *impossible*, not "configured differently". It contradicts "usable by
  everyone / any company" and moves bugs into an opaque DSL that agents and humans
  cannot debug. (This is exactly the Level-2-as-the-only-path failure already
  rejected in IMPLEMENTATION_PLAN §10.3.)

The build so far has invested in the **enforcement substrate** (control plane, 14
arch rules, escape-hatch ledger, 100% gate, audit, events) but left **module
authoring at Level 0**: hand-written FastAPI/SQLModel with `super()` overrides and
implicit lifecycle hooks. The example `tasks` service hand-rolls soft-delete
(`super().base_query()` + a `delete` override); `notes` first emitted events through
a `super().create()` call (a transaction bug) and then through an implicit
`_after_write` override. Both are symptoms: the *enforcement* layer is ahead of the
*authoring* layer.

`super()` and implicit inherited hooks are the specific smell. They are not bad
because they are imperative — they are bad because they are **non-local and
implicit**: a reader (or an agent) cannot understand or verify the file without
spelunking the base class and its MRO, which is precisely how the post-commit emit
bug slipped in.

## Decision

Adopt one **authoring north star**, and make it the lens for every future
module-facing API:

> **Declarative-by-default, constrained-imperative-by-exception, zero implicit
> magic in module files, every deviation on the ledger.**

Concretely:

1. **Reject Target B; commit to Target A.** Drift control on cross-cutting concerns
   is pushed to the extreme (boot + gate, fail-closed). "No code in modules" is
   *not* a goal — genuine business logic stays as code. The honest promise is not
   *no* code, it is **constrained, sandboxed, locally-verifiable** code that cannot
   touch a cross-cutting concern without it turning red in the gate or appearing on
   the escape-hatch ledger.

2. **A module file must be understandable from itself + its declared contract.** No
   `super()` on the module-authoring surface; no implicit inherited hook a reader
   must *know* the base calls. Where the base needs an in-transaction seam (e.g.
   `BaseService._after_write`), it is wrapped by a **declarative** module API so the
   module declares intent rather than overriding a callback. `super()` inside
   framework/capability code is fine; on the **module** surface it is a smell to
   design out.

3. **Common case declarative, escape explicit + local + budgeted.** The 60–70% path
   declares (a model trait, a lifecycle event map, a CRUD router) and writes no
   imperative wiring. The 30–40% path drops to a plain, *constrained* service method
   or native FastAPI/SQLModel — still guarded by the same arch rules, and any
   genuine deviation costs a justified, ratcheted `# arch-allow-*` budget entry.

4. **Every new control still ships as the ADR-0006 quadruple** (typed registry +
   safe default · fail-closed runtime · build-time rule · budgeted escape hatch).
   Declarative sugar that is *not* a control (Tier C) ships without forcing itself
   as the only path: a module may always hand-write the same thing and stay legal.

### The authoring roadmap this unlocks (each a small, green increment)

1. **Declarative lifecycle → event map** (this ADR's first slice): a module declares
   `event_map = LifecycleEventMap(created=…, updated=…, deleted=…)` and the
   framework emits inside the write transaction via `_after_write`. No `super()`, no
   action-branching, no imperative `emit`; the payload is auto-extracted from the row
   by the event's schema. The `events_reference_catalog` rule is extended to police
   the map's event references.
2. **Soft-delete / tenant-scope / timestamps as declared model *traits*.** Declaring
   the trait on the model (a visible mixin) makes `base_query` exclude deleted rows
   and `delete` soft-delete automatically — killing the `tasks` `super().base_query()`
   override. (Mirrors the existing `TenantScopedMixin` precedent.)
3. **`build_crud_router(service, schemas=…, policy=…)`** — an opt-in provider that
   returns a native `APIRouter`, killing the hand-written-CRUD drift surface without
   a DSL. A custom module still hand-writes its router.
4. **`terp new module` scaffolding + a one-page-per-concern agent cookbook** — emit
   readable Level-1 code the owner keeps; never a runtime black box.

## Consequences

- The next track is **authoring ergonomics**, not more enforcement depth. Success is
  measured by "how little, and how declarative, is a typical module" — not by rule
  count.
- The honest ceiling is explicit: custom business logic remains code. Terp's win is
  that such code is **sandboxed** (no engine, no network, no cross-module/`_internal`
  imports, no minted permission/event) and every step outside the pattern is on the
  ledger — so a remote auditor reviews two small diffs, not every file.
- The realistic agent loop is **write → gate fails with a precise, fixable reason →
  fix**, not "make modules so declarative an agent cannot err" (impossible). The
  arch harness's exact, line-level messages are a feature of that loop.
- `super()` and implicit hooks are progressively **designed out of the module
  surface** as each declarative API lands; they remain legal inside the framework.

## Decision

Status: **Accepted** — the north star is *declarative-by-default,
constrained-imperative-by-exception, zero implicit magic in modules, every deviation
ledgered*. Target A (anti-drift on cross-cutting concerns) is pursued to the extreme;
Target B (no-code modules) is explicitly rejected to keep Terp usable by everyone.
The authoring-ergonomics roadmap (lifecycle event map → model traits → CRUD router →
scaffolding) opens with the declarative `LifecycleEventMap`.
