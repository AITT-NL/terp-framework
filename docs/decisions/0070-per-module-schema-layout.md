# 0070 - Per-module schema layout (opt-in physical separation)

- **Status:** Accepted
- **Date:** 2026-07-05
- **Context phase:** The schema-separation direction accepted in ADR 0069, now
  implemented as the promised follow-up slice
- **Supersedes/relates:** [ADR 0069](0069-verified-database-dialects-and-schema-direction.md)
  (direction + the rejected `schema_translate_map` design),
  [ADR 0027](0027-packaged-migrations-per-package-histories.md) (per-package
  histories), [ADR 0011](0011-model-traits-vs-control-plane-policy.md) (deployment
  owns the *how*)

---

## Decision

A deployment can opt into **physical per-module separation** of its tables:
`DB_SCHEMA_LAYOUT="per-module"` places each migration-owning package's tables in
a PostgreSQL schema named after its migration label (`notes`, `audit`, …). The
default stays `flat` (every table in the default schema, any dialect) — the
layout is a Tier-B deployment knob, never a module author's concern.

### How the layout is applied (the `search_path` recipe, per ADR 0069)

Model metadata stays **schema-free forever**; the layout lives entirely in the
migration subsystem:

1. **Routing app connections** — `terp migrate upgrade` (per-module) first runs
   `CREATE SCHEMA IF NOT EXISTS` per package plus **`ALTER DATABASE … SET
   search_path`** (own schemas first, `public` last). The *database* then serves
   every future connection — the app engine, `psql`, a BI tool — a search_path
   that resolves unqualified table names, so `terp.core` needs zero layout
   knowledge and the layer-0 boundary stays clean.
2. **Routing migration DDL** — each package's Alembic run opens with
   `CREATE SCHEMA IF NOT EXISTS "<label>"` + a session
   `SET search_path TO "<label>", <other labels…>, "public"` (own schema
   **first**: PostgreSQL creates unqualified tables in the first entry, which is
   how token-free revisions land in their package's schema; the other labels
   keep cross-module FK targets resolvable). The setup transaction is
   **committed before Alembic configures** — Alembic treats a connection with an
   in-progress transaction as caller-managed and would otherwise never commit
   the DDL (a silent full rollback, caught live by the PG lane).
3. **Version tables stay in `public`** (`version_table_schema` pinned), so
   `migration_status`, `terp migrate check`, and the pending-migrations boot
   guard read through a plain connection, completely layout-unaware.
4. **Reflection** — the run pins `connection.dialect.default_schema_name` to the
   package schema (the documented Alembic multi-tenancy recipe), keeping
   autogenerate and the `assert_migrations_match_models` drift check meaningful
   under the layout; both accept `schema_layout=` and are green on live
   PostgreSQL in the conformance lane.
5. **Brownfield adoption** — `terp migrate adopt-schemas` moves an existing flat
   database's owned tables via `ALTER TABLE … SET SCHEMA` (data, indexes, and
   constraints move with the table; idempotent; version tables stay), then pins
   the database search_path. The `stamp` analogue for layout.

### Enforcement (the ADR 0006 quadruple)

| Layer | Control |
|---|---|
| Runtime (fail-closed) | `per-module` off PostgreSQL: refused at engine construction, at production boot (`Settings`), and by every migration entry point (`MigrationError`) |
| Build-time | New `no_manual_table_schema` rule: a hand-written `__table_args__ = {"schema": …}` in an app module pins a table outside the managed layout (and breaks SQLite dev/test) — flagged, budgeted escape hatch available |
| CI | The per-module conformance tests run in the `postgres-lane` job: placement, plain-connection resolution, drift check, downgrade, and `adopt-schemas` round-trip |
| Default | `flat` — byte-identical to every existing deployment; SQLite dev/test untouched |

## What this buys (and still does not)

Physical separation enables per-schema operations — most importantly
**per-schema `GRANT`s to distinct database roles**, the layer at which the
*database itself* refuses cross-module access. That Tier-2 roles/GRANTs work is
deliberately its own future decision (real operational cost: role provisioning,
owner-vs-runtime roles). Schemas alone remain namespacing + blast-radius
clarity: unqualified raw SQL still resolves through the search_path, and the
code-level guards (`no_cross_module_imports`, service-only writes) remain the
primary prevention.

## Consequences

- A consumer flips one env var (`DB_SCHEMA_LAYOUT=per-module`) on a fresh
  database, or runs `terp migrate adopt-schemas` once on an existing one.
  Switching back is not automated (move tables manually); the knob is
  deployment-sticky by design.
- Every `terp migrate` subcommand accepts `--schema-layout` as an explicit
  override of the settings default.
- The layout assumes the default PostgreSQL `public` schema exists (version
  tables and the search_path tail); exotic clusters without `public` are out of
  scope for now.
- The example app and the template stay on `flat`; nothing changes for them
  until a deployment opts in.
