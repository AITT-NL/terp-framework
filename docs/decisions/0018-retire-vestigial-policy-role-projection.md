# 0018 - Retire the vestigial `Policy.read_role` / `write_role` projection

- **Status:** Accepted
- **Date:** 2026-06-24
- **Context phase:** Phase 2 (base profile), a code-quality / tech-debt pass
- **Relates:** [ADR 0002](0002-control-plane-and-auditable-module-authority.md)
  (typed control-plane authority), [ADR 0004](0004-typed-principal-role.md) (made the
  typed `AuthorizationRequirement` the enforcement path and flagged
  `Policy.read_role` / `write_role` for later removal).

---

## Context

[ADR 0004](0004-typed-principal-role.md) made the typed `read_requirement` /
`write_requirement` (an `AuthorizationRequirement` carrying kind + name + min-rank)
the **only** authorization path the guard and the control plane use. For
backward-compatibility it kept `Policy.read_role` / `write_role` as a `Roles`-enum
*projection* of the requirement, computed on every `Policy` construction by a
`_legacy_role` helper, "to be retired later."

A code-quality audit confirmed those fields now have **zero production consumers**:

- `build_guard` authorizes on `read_requirement` / `write_requirement`.
- The CLI authority map (`terp inspect control-plane`) renders
  `read_requirement.label` / `write_requirement.label`.
- Only a handful of unit tests asserted the `read_role` / `write_role` projection.

So `_legacy_role` was dead weight recomputed on every policy, and the two fields were
a second, redundant authority representation — exactly the kind of drift the typed
model was meant to remove.

## Decision

Remove `Policy.read_role` / `write_role` and the `_legacy_role` helper.

- The `read_role=` / `write_role=` **constructor parameters stay** — they are a
  convenient alias for tier policies expressed with the bundled `Roles` enum
  (`Policy(read_role=Roles.ADMIN, …)`), and they normalize into
  `read_requirement` / `write_requirement` exactly like `read=` / `write=` do. So
  `Policy` now has a single, uniform authority **output** (the typed requirements)
  regardless of which input alias was used.
- `Roles` (the bundled default ladder) and `Policy.tiers()` are unaffected.
- The `terp.arch` `no_adhoc_permission_literals` keyword set is unchanged (it scans
  the input kwargs, which remain).

## Consequences

- One authority representation on `Policy`, not two; no projection recomputed per
  construction; a smaller, clearer kernel surface.
- A purely internal cleanup: there are no external consumers (nothing is published or
  pushed), and the typed requirements — the thing everything already used — are
  untouched.
- 311 tests, 100% framework line coverage.
