# 0061 - Visibility-based read scope: the second divergent scope-registry consumer (Phase 8)

- **Status:** Accepted
- **Date:** 2026-07-03
- **Context phase:** Phase 8 (dogfood: 2nd divergent tenancy strategy)
- **Relates:** [ADR 0017](0017-non-overridable-scope-predicate-and-registry.md) (the
  non-overridable row-scope registry this consumes), [ADR 0029](0029-object-level-ownership-authorization.md)
  (the per-row *write* gate; it explicitly deferred the per-owner *read*-visibility
  predicate to "the consumer registers it"), [ADR 0021](0021-create-app-middleware-seam.md)
  (the tenancy-agnostic kernel claim this validates).

---

## Context

Design §13 Phase 8 required a **second, divergent consumer** of the row-scope seam to
validate that `terp.core` is genuinely tenancy-agnostic — that the registry (ADR 0017)
is a general read-visibility port, not a tenant filter with a generic name. Until now
the registry had exactly one consumer: `terp-cap-tenancy`'s `TenantScopedMixin`
predicate (partition rows by an ambient tenant claim, fail closed without one).

ADR 0029 had already named the shape of the second strategy: `journals` rows are
owner-*written* through the central `OwnedMixin` gate, but read visibility was
deliberately left open, with hiding other owners' rows deferred to a
consumer-registered ADR 0017 predicate.

## Decision

**Ship a visibility-based read scope on the example app's `journals` module, as
app-level consumer code — no new capability, no core strategy code.**

- `Journal` gains a `visibility` column — `"shared"` (the default; readable by anyone
  the coarse role policy admits) or `"private"` (visible only to its owner). Plain
  capped `str`, like `Task.status` — the *predicate*, not an enum, is the security
  boundary.
- `journals/models.py` registers `_journal_visibility_predicate` at import (exactly
  like `TenantScopedMixin` registers the tenant predicate): for `Journal` reads it
  appends `visibility == "shared" OR owner_id == current_actor_id()`. Any *other*
  visibility value is owner-only — an unknown state never widens reads (fail closed).
  An anonymous context (`current_actor_id()` → `None`) matches no owner, so it sees
  only shared rows.
- `terp.core` gains one tiny public read seam: **`current_actor_id()`** — the read
  half of the actor binding `bind_audit_actor` installs per request (`terp.core.audit`).
  A caller-keyed predicate needs the current actor; threading a principal through
  service calls or reaching into the context var directly were the alternatives.
- The predicate's `owner_id` comparison is the module's **one governed opt-out**:
  `no_manual_ownership_checks` polices exactly this attribute access in app code, and
  this line *is* the consumer-registered read-visibility predicate that rule (via
  ADR 0029) points to — so it carries a justified
  `# arch-allow-no-manual-ownership-checks` marker, counted by the example app's
  `escape-hatch-budget.json` (bumped `{}` → 1). The mirror of how `terp-cap-tenancy`
  holds the single `no_manual_scope_filtering` opt-out for the tenant predicate — the
  escape hatch exists precisely for the code that *implements* a seam.

## What this validates

- **The kernel is strategy-agnostic.** Two consumers with nothing in common — an
  ambient-claim partition (tenancy) and a caller-keyed row opt-out (visibility) —
  compose on the same `register_scope_predicate` port, each guarding on its own
  model, with soft-delete stacking underneath. `terp.core` changed by one read
  accessor; no strategy code entered the kernel.
- **The layered read/write split holds.** Writes stay on the central `OwnedMixin`
  gate (403 for a non-owner); reads are scoped (a hidden row 404s — it does not
  exist for that caller). Neither seam leaks into module service/router code.
- **The governance story round-trips.** The one hand-written `owner_id` reference in
  the example app is visible, justified, and budgeted — the harness dogfood
  (`assert_app_clean(_EXAMPLE_APP, budget_path=...)`) now exercises the budget path
  on the real app.

## Consequences

- Phase 8 closes: the example app dogfoods both divergent strategies (`projects` =
  tenant-partitioned, `journals` = owner-visibility) plus their composition with the
  ownership write gate.
- A future first-class trait (`VisibilityScopedMixin` in a capability) stays open as
  sugar if a second app wants the same strategy — the seam and semantics are now
  proven; packaging is a separate decision (per ADR 0060's classification bar it must
  earn cross-cutting status first).
- The journals migration history gains one revision (`add journal visibility`,
  server-default `shared`, so existing rows keep their pre-ADR readable behavior).
