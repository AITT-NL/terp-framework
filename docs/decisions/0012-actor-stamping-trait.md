# 0012 - Actor-stamping as an auto-honored model trait (+ no_manual_actor_stamping)

- **Status:** Accepted
- **Date:** 2026-06-24
- **Context phase:** ADR 0009 authoring track, slice 3 (model traits)
- **Relates:** [ADR 0009](0009-authoring-model-and-opinionation-boundary.md) (north
  star), [ADR 0010](0010-soft-delete-trait-and-no-manual-scope-filtering.md) (the
  soft-delete trait this mirrors), [ADR 0011](0011-model-traits-vs-control-plane-policy.md)
  (the which/how boundary), [ADR 0007](0007-audit-auto-emit-and-the-audit-seam.md)
  (the `_save` audited chokepoint + the `audit_actor_ctx` seam this rides)

---

## Context

ADR 0009 set the authoring north star (*declarative-by-default, zero implicit magic
in module files*) and ADR 0010 delivered its first model trait: soft-delete is now
**auto-honored** by `BaseService`, declared once on the model. ADR 0010's mixin
survey named **actor-stamping** (`created_by` / `modified_by`) as the strongest
remaining mixin to re-author generically.

Who created and last modified a row is **provenance** — a cross-cutting concern,
not business logic. Two shapes were on the table:

1. **Module-set** — each service writes `row.created_by_id = …` itself. This is the
   exact per-module drift ADR 0009 designs out, *and* it is a security hazard: the
   actor would come from caller-reachable code (or worse, a request body), so it can
   be **forged**.
2. **Auto-fill** — the framework stamps the actor centrally, from the single write
   chokepoint, using the **authenticated request principal** (never caller data).

## Decision

Adopt **auto-fill**, mirroring the soft-delete trait (ADR 0010) and policed by a new
two-layer `no_manual_actor_stamping` rule.

1. **Declare the trait once, on the model.** `class Note(BaseTable,
   ActorStampedMixin, table=True)` is the whole declaration. The new core
   `ActorStampedMixin` supplies two **FK-less**, nullable UUID columns
   (`created_by_id` / `modified_by_id`); this slice supplies the **behaviour**.

2. **`BaseService` fills it automatically.** In the single `_save` chokepoint, when
   the row composes `ActorStampedMixin`, the request actor (read from
   `audit_actor_ctx` — the same request-scoped seam the audit trail binds) is written
   to `created_by_id` **once on insert** and to `modified_by_id` **on every save**.
   Because a soft-delete routes through `_save` (ADR 0010), it records *who* deleted.
   A module writes **zero** stamping code.

3. **`no_manual_actor_stamping` (build-time).** A module may not set or compare
   `created_by_id` / `modified_by_id` by hand — the actor must come from the
   authenticated request, never from module logic or caller-supplied data. Hand-set
   provenance is forged provenance. Registered in `_ALL_RULES`, paired with
   `test_no_manual_actor_stamping`, enforced by the self-completeness meta-test. (As
   with the scope columns, a read DTO may still *expose* the column; only attribute
   access is policed.)

### Why FK-less, nullable UUIDs

The ids are deliberately **FK-less** — like the audit record's `actor_id` and the
access grant's `subject_id`. `terp.core` is layer 0 and must not import a user table
(`§3.7`), and a principal may not even *be* a user (a service account, an external
subject). The columns are **nullable** and best-effort: a write outside a request (a
worker, a migration, an unauthenticated path) leaves them `None` rather than failing.
Making an actor *required* is a future control-plane **how** knob (ADR 0011), not a
column default — the trait owns only the *which*.

### Why key the stamp off the entity, not `self.model`

`_save` already operates on the **row in hand** (it derives the audit target from
`type(entity)`, never `self.model`). Keeping the stamp keyed off the entity
(`isinstance(entity, ActorStampedMixin)`) preserves that: a bespoke `_save` call with
a non-model object (e.g. the event-hook unit path) must not be forced to declare
`self.model`. For real CRUD `entity` is always an instance of `self.model`, so the two
are equivalent — `isinstance` is just the more robust spelling here. (The soft-delete
trait keys off `self.model` because `base_query` / `delete` act at the *type* level,
before any row exists.)

### Why auto-fill over module-set or a central registry

- **Unspoofable.** The actor is resolved from the authenticated principal at the
  chokepoint, so it cannot be set from a request body or a module mistake.
- **Single source of truth + composition.** The trait is declared once (the mixin)
  and contributes one more orthogonal step in the same `_save` — no `super()` chains,
  no `ActorStampedSoftDeleteService` combinatorics (the ADR 0009 smell).
- **The which/how boundary (ADR 0011).** The model declares *which* tables are
  stamped; a future `control_plane/database.py` policy may later tune the *how*
  (required vs. best-effort outside a request, stamping a system actor for jobs)
  without a central list of leaf tables.

### Honest divergence from convention

A conventional `AuthoredMixin` carried a **foreign key** to its user
table and was populated by hand in places. Terp re-authors it generically: the FK is
**dropped** (low-layer purity + non-user principals), and the fill is **automatic and
unspoofable** rather than caller-driven. As with soft-delete, the behaviour follows
from a **visible declaration** on the model, and `terp inspect` will later surface
each model's traits (`Note: actor-stamped ✓`).

### Mixin survey status (updated)

| Trait | Status | Shape |
|---|---|---|
| UUID PK · timestamps · OCC `version` | ✅ done | Always-on `BaseTable` traits. |
| Soft-delete (`deleted_at`) | ✅ ADR 0010 | Opt-in, auto-honored by `BaseService`. |
| **Actor-stamping** (`created_by_id` / `modified_by_id`) | ✅ **this ADR** | Opt-in, **auto-filled in `_save`** from the request actor; FK-less, nullable, best-effort. |
| Tenant scope (`tenant_id`) | 🟡 in `terp-cap-tenancy` | `TenantScopedService` base; converges to the auto-honor predicate-registry model later. |
| Address (value object) | ⬜ low priority | Columns only, no behaviour — re-author generically if a neutral app proves the need. |

## Consequences

- The example `notes` and `tasks` modules dogfood the trait with **zero** stamping
  code. `tasks` demonstrates the **composition**: `BaseTable + SoftDeleteMixin +
  ActorStampedMixin` — a soft-delete both hides the row *and* records who deleted it
  via `modified_by_id`, while `created_by_id` is preserved.
- `BaseService._save` now auto-honors two model traits (soft-delete behaviour in
  `delete`, actor-stamping in `_save`) plus audit auto-emit, all from one chokepoint.
- The next authoring slices remain `build_crud_router` (Level 1 sugar) and the
  scope-predicate registry (converging tenancy under `no_manual_scope_filtering`);
  value-object mixins stay low priority.

## Decision

Status: **Accepted** — actor-stamping is an auto-honored, opt-in model trait
(`ActorStampedMixin`; `BaseService._save` fills `created_by_id` on insert and
`modified_by_id` on every save from the request actor), enforced by the two-layer
`no_manual_actor_stamping` rule, with FK-less nullable best-effort ids. Gate: **243
passed, 100% line coverage**; the example `notes` + `tasks` modules dogfood the
trait with zero stamping code and an escape-hatch budget of `{}`.
