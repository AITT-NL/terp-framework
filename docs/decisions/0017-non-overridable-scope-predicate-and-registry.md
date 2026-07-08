# 0017 - Non-overridable scope predicate + the row-scope registry

- **Status:** Accepted
- **Date:** 2026-06-24
- **Context phase:** Phase 2 (base profile), adversarial-review follow-ups
- **Relates:** [ADR 0009](0009-authoring-model-and-opinionation-boundary.md)
  (``super()`` on the module surface is a smell — design it out),
  [ADR 0010](0010-soft-delete-trait-and-no-manual-scope-filtering.md) (auto-honored
  soft-delete + ``no_manual_scope_filtering``), [ADR 0011](0011-model-traits-vs-control-plane-policy.md)
  (the scope-predicate registry was foreshadowed here). Finding: **H2** in
  [docs/reviews/2026-06-24-adversarial-design-review.md](../internal/reviews/2026-06-24-adversarial-design-review.md).

---

## Context

``BaseService.base_query`` was the single read-scoping seam **and** an override
point — its own docstring *invited* "override only to add genuine business filters."
A subclass that wrote ``return select(self.model).where(...)`` instead of
``return super().base_query().where(...)`` silently dropped ``deleted_at IS NULL``
and (for a ``TenantScopedService`` subclass) the **tenant predicate** — an IDOR /
cross-tenant read leak (H2). The ``no_manual_scope_filtering`` rule did not catch it:
you do not need to *reference* a managed column to drop the filter, you just omit the
``super()`` call. And the framework's own ``TenantScopedService`` modelled the exact
pattern — a ``super().base_query()`` override — making ``super()`` look like the
sanctioned way to scope, against the ADR-0009 principle that ``super()`` on the
module surface is a smell to design out.

## Decision

Make row scope a **non-droppable, central composition**, and give modules a
``super()``-free hook for the only thing they should add: business filters.

1. **`business_filters()` — the module hook.** ``BaseService.business_filters(self)
   -> Sequence[ColumnElement[bool]]`` (default empty) is what a module overrides to
   **add** static read conditions. It returns *conditions*, not a query, so it can
   only narrow a read — there is **no ``super()`` to remember and no way to widen or
   drop the framework's scope.** (A per-call dynamic filter still belongs in a custom
   ``list`` that builds on ``base_query().where(...)`` — as ``tasks`` does for its
   ``status`` filter.)

2. **`base_query()` is non-overridable.** It composes, centrally: ``select(model)`` +
   the built-in soft-delete scope + every registered row predicate + the service's
   ``business_filters()``. The new ``terp.arch`` **``base_query_not_overridden``** rule
   flags any service that defines ``base_query`` (build-time), and the only blessed,
   structurally-safe extension is ``business_filters`` (runtime) — the two-layer pair.

3. **Row-scope registry (`terp.core.scoping`).** ``register_scope_predicate(predicate)``
   lets a capability plug a row-visibility predicate into the kernel **without the
   kernel importing it** (the foreshadowed registry, ADR 0011). Soft-delete stays the
   kernel's built-in; **tenancy now registers its tenant predicate** at import instead
   of overriding ``base_query`` — so the capability no longer uses ``super()`` either,
   and reads of *any* tenant-scoped model are filtered centrally. A predicate guards on
   its mixin and is a no-op for models it does not own.

4. **`TenantScopedService` slims to write-stamping.** Its ``base_query`` override is
   gone; it now only stamps ``tenant_id`` on ``create`` (through the audited
   chokepoint). The ``tenant_scoped_models_use_scoped_service`` rule consequently
   guards the **write** side (a tenant model must use the scoped service so inserts are
   stamped); reads are already scoped by the registered predicate.

## Consequences

- A ``super()``-less ``base_query`` override can no longer silently drop soft-delete
  or tenant scope: there is no ``base_query`` to override (the rule forbids it), and
  the module hook (``business_filters``) is structurally incapable of widening a read.
- **No ``super()`` on the module surface for scoping**, and none in the tenancy
  capability either — the registry composes predicates centrally (honoring ADR 0009).
- The **scope-predicate registry** backlog item is delivered: a capability contributes
  row visibility through one registration, and the kernel stays tenancy-agnostic.
- Tenancy's single governed ``# arch-allow-no-manual-scope-filtering`` opt-out simply
  moved from the old ``base_query`` override to the registered predicate (budget
  unchanged at 1).
- 310 tests, 100% framework line coverage.
- **Still open (sequenced):** H3 (forbid a ``table=True`` ``response_model``), a
  first-class **object-level / ownership** authorization seam (the per-row complement),
  and first-class tenancy/role wiring (H7/H8).
