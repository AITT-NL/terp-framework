# 0011 - Model traits vs. control-plane policy (the which/how boundary)

- **Status:** Accepted
- **Date:** 2026-06-24
- **Context phase:** ADR 0009 authoring track, after ADR 0010 soft-delete trait
- **Relates:** [ADR 0009](0009-authoring-model-and-opinionation-boundary.md)
  (declarative-by-default), [ADR 0010](0010-soft-delete-trait-and-no-manual-scope-filtering.md)
  (soft-delete trait), [docs/IMPLEMENTATION_PLAN.md](../internal/IMPLEMENTATION_PLAN.md) §3.2
  (`DatabaseConfig`) + §10 (Tier A/B/C)

---

## Context

ADR 0010 made soft-delete an auto-honored model trait: a table composes
`SoftDeleteMixin`, and `BaseService` excludes deleted rows and soft-deletes that
model automatically. That raised the natural long-horizon question: should this
instead be declared centrally in a future `control_plane/database.py`, e.g. a
`SoftDeletePolicy` / `DatabasePolicy` that defaults soft-delete on for all tables
and lets the owner specify which tables opt in or out? The same question applies to
other trait-like concerns: tenant scoping, actor-stamping, retention, table naming,
route prefixing, and future database operations.

The control plane is powerful because it centralizes *shared vocabularies* and
*app-wide singletons*: permissions, events, audit policy, security config. But if
we centralize every per-model property, the control plane starts enumerating leaf
module implementation details. That would invert the dependency direction (§3.7),
reintroduce bare-string drift (table names in lists), and make module files less
locally understandable — exactly what ADR 0009 rejects.

## Decision

Adopt the **which/how boundary**:

> **Traits on the model declare _which_ rows have a property. Control-plane policies
> configure _how_ that property behaves app-wide.**

### What belongs on the model (the *which*)

Per-model intrinsic properties live next to the model, as visible traits:

- `SoftDeleteMixin`: this table is soft-deletable.
- `TenantScopedMixin`: this table participates in tenant scoping.
- Future `ActorStampedMixin`: this table stores creator / last-editor identifiers.
- Future value-object mixins (e.g. address fields): this table owns those columns.

This keeps a module locally readable: opening the model shows its traits. There is
no second central list to keep in sync, no `super()` service base to remember, and
no stringly typed table registry.

### What belongs in `control_plane/database.py` (the *how*)

Future database policy registries configure **behavioural knobs**, never the list of
leaf tables that have a trait:

- soft-delete retention / purge schedule;
- whether privileged reads may include deleted rows;
- hard-delete escape policy (who may permanently erase a soft-deleted row);
- table-name and schema naming patterns;
- engine / schema / migration locations;
- tenant binding strategy or scope-predicate provider;
- actor-stamping behaviour (e.g. required vs. best-effort outside a request).

A `SoftDeletePolicy` or `DatabasePolicy` is therefore welcome **when there is
behaviour to tune**. It must not become `soft_delete_tables=[...]` or
`soft_delete_except=[...]`.

### Rejected: a central table allow/deny list

Do **not** make `DatabasePolicy` enumerate which tables are soft-deletable (or
which are tenant-scoped / actor-stamped):

1. **Dependency inversion.** A typed central list would force `control_plane/` to
   import leaf module models, which §3.7 forbids. A string list avoids the import but
   reintroduces typo drift.
2. **Action at a distance.** Reading `Task` would not reveal that it is
   soft-deletable; the reader or agent would need to know a second file exists and
   keep both files synchronized.
3. **Defaults become footguns.** Soft-delete-on-for-all is often wrong: append-only
   logs, event outbox rows, link tables, and erasure paths should not accumulate
   soft-deleted ghosts by accident. The safe default for this trait is **off unless
   declared**, not globally on.
4. **A central view does not require central ownership.** `terp inspect` can generate
   a model-traits report (`Task: soft-delete ✓`, `User: actor-stamped ✓`) without
   making that report the source of truth.

### If an app wants a different default

An application may define its own base model to make a trait the local default,
while keeping the declaration visible and local:

```python
class AppTable(BaseTable, SoftDeleteMixin):
    """This app's default row base: soft-deletable unless a table opts out."""

class Task(AppTable, table=True):
    ...

class AppendOnlyLog(BaseTable, table=True):
    ...  # hard-delete / append-only semantics remain explicit
```

This gives "default on, explicit opt-out" ergonomics without a central table list.

## General rule for future registries

Use two tests before creating or extending a control-plane registry:

1. **Shared-or-property?** Shared vocabulary or app-wide singleton -> control plane.
   Intrinsic property of one model/module -> declare it on that model/module.
2. **Dependency direction?** If the central registry must enumerate leaf module
   classes or table names, it is probably misplaced. The control plane is referenced
   by modules; it should not import leaf implementation code.

## Consequences

- ADR 0010's soft-delete implementation stays as-is: model trait = source of truth,
  `BaseService` auto-honors it, `no_manual_scope_filtering` forbids hand-written
  scope predicates.
- A future `DatabaseConfig` / `DatabasePolicy` remains planned, but it should be
  introduced only when there is real app-wide behaviour to configure (retention,
  purge, naming, engine/schema/migrations, tenant binding), not as a speculative
  central list of model traits.
- `terp inspect` becomes the central **view** of model traits and policies, without
  becoming the central **source**. This preserves auditability without moving
  intrinsic model facts away from the model.
- The same boundary applies to tenant scoping and actor-stamping: declare the trait
  on the model; configure the global semantics in the relevant registry only when
  the behaviour is app-wide and shared.

## Decision

Status: **Accepted** — model traits own the *which*; control-plane/database policies
own the *how*. Central table allow/deny lists are rejected. The next database-policy
work should be behaviour-driven (retention/purge/naming/migration/tenant binding),
while `terp inspect` provides the central generated view of traits.