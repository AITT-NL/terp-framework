# 0010 - Soft-delete as an auto-honored model trait (+ no_manual_scope_filtering)

- **Status:** Accepted
- **Date:** 2026-06-24
- **Context phase:** ADR 0009 authoring track, slice 2 (model traits)
- **Relates:** [ADR 0009](0009-authoring-model-and-opinionation-boundary.md) (north
  star), [docs/IMPLEMENTATION_PLAN.md](../internal/IMPLEMENTATION_PLAN.md) §3.6
  (`no_manual_scope_filtering`), [ADR 0007](0007-audit-auto-emit-and-the-audit-seam.md)
  (the `_save` / `_remove` audited chokepoint this rides)

---

## Context

ADR 0009 set the authoring north star: *declarative-by-default, zero implicit magic
in module files*. Its second slice tackles the example app's messiest module —
`tasks` — which hand-wrote soft-delete as a `super().base_query()` override **and** a
`delete` override **and** a `_utc_now` helper. Soft-delete is a **cross-cutting
concern**, not business logic, so forcing each module to re-implement it imperatively
(with `super()`, the exact smell ADR 0009 designs out) is precisely the drift we want
gone.

Two implementation shapes were on the table: (a) a `SoftDeleteService` base + an arch
rule requiring soft-delete models to use it (mirroring the tenancy
`TenantScopedService` pattern), or (b) **auto-honor** the trait directly in
`BaseService`, keyed off the model's `SoftDeleteMixin`, with no service-base choice.

## Decision

Adopt **(b) auto-honor**, and police drift with the `no_manual_scope_filtering` rule
already named in design §3.6.

1. **Declare the trait once, on the model.** `class Task(BaseTable, SoftDeleteMixin,
   table=True)` is the whole declaration. `SoftDeleteMixin` (already in `terp.core`)
   supplies the `deleted_at` column; this slice supplies the **behaviour**.

2. **`BaseService` honours it automatically.** `base_query()` adds
   `where(deleted_at IS NULL)` when `issubclass(self.model, SoftDeleteMixin)`, so
   every `get` / `list` excludes soft-deleted rows; `delete()` becomes a **soft**
   delete for such models (stamp `deleted_at`, route through the audited `_save`) and
   stays a hard delete (`_remove`) otherwise. A module writes **zero** soft-delete
   code — `TaskService` collapses to `model = Task` plus its one genuine business
   filter (`list(status=…)`).

3. **`no_manual_scope_filtering` (build-time).** A module may not reference a
   framework-managed scope column (`deleted_at` / `tenant_id`) — to filter, set, or
   compare — because the framework applies that predicate centrally. Hand-rolling it
   can leak or destroy scoped rows. Registered in `_ALL_RULES`, paired with
   `test_no_manual_scope_filtering`, enforced by the self-completeness meta-test. (A
   read DTO may still *expose* the column; only attribute access is policed.)

### Why auto-honor over a `SoftDeleteService` base

- **Composition.** Row-scoping traits (soft-delete, tenant, later visibility) each
  contribute one predicate ANDed in a single `base_query` — no
  `TenantScopedSoftDeleteService` combinatorics or `super()`-chained overrides (the
  ADR 0009 smell).
- **Single source of truth.** The trait is declared once (the mixin); there is no
  second `…Service` declaration that can drift, hence no rule needed just to keep two
  declarations in sync.
- **It is the documented end-state.** §3.6 specifies "session-level predicate is the
  only path" + `no_manual_scope_filtering` — the centralized-predicate model, not
  per-trait service bases. (`TenantScopedService` is the earlier interim; it converges
  here later via a scope-predicate registry so a *capability* can plug its predicate
  into core `base_query` without core importing it.)
- **Core owns the column.** `SoftDeleteMixin` already lives in `terp.core`, so core
  `BaseService` honouring it keeps the mechanism in one layer.

### Honest divergence from convention

The conventional approach **deliberately did not** auto-filter soft-deleted rows — its
`SoftDeleteMixin` docstring warns that "magic filters surprise people debugging a
missing row at 2am", leaving each caller to filter by hand. Terp **inverts** that
trade-off on purpose: hand-filtering is exactly the drift we forbid. The "2am" risk is
mitigated three ways — the behaviour follows from a **visible declaration** on the
model (not hidden magic), the `no_manual_scope_filtering` rule makes the managed column
off-limits to ad-hoc queries, and `terp inspect` will surface each model's traits
(`Task: soft-delete ✓`). Explicit "include deleted" / hard-delete remain deliberate,
narrow escape paths (future work), never the silent default.

### Mixin survey (which traits fit this model)

Re-authored generically from conventional mixins:

| Trait | Status | Shape |
|---|---|---|
| UUID PK · timestamps · **OCC `version`** | ✅ done | **Always-on** `BaseTable` traits (the framework owns the behaviour — OCC is the precedent for "trait behaviour lives in the framework, not the module"). |
| **Soft-delete** (`deleted_at`) | ✅ this ADR | Opt-in, **auto-honored** by `BaseService`. |
| **Actor-stamping** (`created_by` / `modified_by`) | ⬜ recommended next | Opt-in mixin; **auto-filled in `_save`** from the request actor context (the same `audit_actor_ctx` the audit seam binds). FK-less UUIDs (like `AuditEvent.actor_id` / the access grant), so the low layer never imports the user table. |
| **Tenant scope** (`tenant_id`) | 🟡 in `terp-cap-tenancy` | Currently a `TenantScopedService` base; converges to the auto-honor predicate-registry model later. |
| **Address** (value object) | ⬜ low priority | Columns only, **no behaviour** — re-author generically (no company terms) if a neutral app proves the need. |

## Consequences

- `tasks` is no longer a "Level 0 imperative override" module; it is a declaration
  plus one business filter — the clearest demonstration yet of the ADR 0009 boundary
  (cross-cutting → declared trait; business logic → stays as code).
- `BaseService.delete` is now polymorphic (soft vs hard) by trait; both paths remain
  audited.
- The next authoring slice is **actor-stamping** (the strongest remaining mixin),
  then `build_crud_router`; the **scope-predicate registry** (unifying tenancy under
  `no_manual_scope_filtering`) is the convergence follow-on.

## Decision

Status: **Accepted** — soft-delete is an auto-honored model trait
(`BaseService.base_query` excludes deleted rows; `delete` soft-deletes), enforced by
the two-layer `no_manual_scope_filtering` rule, chosen over a service-base for
composition + single-source-of-truth + alignment with §3.6. Gate: **235 passed, 100%
line coverage**; the example `tasks` module dogfoods the trait with zero soft-delete
code and an escape-hatch budget of `{}`.
