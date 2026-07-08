# 0072 — Database additivity review: offline SQL, soft-delete unique guard, recorded posture

- **Status:** Accepted
- **Date:** 2026-07-05
- **Relates to:** [ADR 0010](0010-soft-delete-trait-and-no-manual-scope-filtering.md)
  (soft-delete trait), [ADR 0027](0027-packaged-migrations-per-package-histories.md)
  (per-package histories), [ADR 0064](0064-keyset-cursor-pagination.md) (keyset
  pagination), [ADR 0069](0069-verified-database-dialects-and-schema-direction.md)
  (verified dialects), [ADR 0070](0070-per-module-schema-layout.md) (schema layout),
  [ADR 0071](0071-runtime-role-privilege-split.md) (role split)

## Context

A design review asked one question of the whole database tier: **can every
foreseeable need be met by *additions*, or is a breaking refactor lurking?** The
classic one-way doors were audited: constraint naming conventions (retrofit =
rename every constraint in every deployed database), native DB enums (`ALTER
TYPE` forever), schema names authored into models, ALTER migrations breaking the
SQLite dev loop, a shared Alembic graph, offset-only pagination, PK type churn,
dialect lock-in via raw SQL, blobs in tables, and kernel-owned tables.

**Finding: all already closed.** The naming convention is installed on the shared
metadata at import; no `sa.Enum` exists anywhere (status columns are deliberate
plain strings); `no_manual_table_schema` keeps metadata schema-free so layout is
pure deployment config; `render_as_batch` is dialect-gated; histories are
per-package and linear; keyset pagination ships alongside `Page[T]`; keys are
portable `Uuid` columns; capabilities contain zero raw SQL; files stream to a
`StorageBackend`; `terp.core` owns no tables and the engine module is private.

Two genuine gaps remained (both additive), plus stances worth recording so a
future maintainer does not mistake a deliberate choice for an accident.

## Decision

1. **Soft-delete × unique guard** — new `terp.arch` rule
   `no_unique_columns_on_soft_delete_models`: a table that composes
   `SoftDeleteMixin` — **directly or through an app-owned base**
   (`class AppTable(BaseTable, SoftDeleteMixin)`, the ADR 0011 pattern; the rule
   computes the inheritance taint closure tree-wide) — may not declare a
   full-table unique constraint (`Field(unique=True)`, `UniqueConstraint(...)`,
   or `Index(..., unique=True)`). A soft-deleted row keeps occupying the index,
   so the "deleted" value can never be reused — an inexplicable 409 long after
   the delete. The fix the rule accepts: a **partial unique index scoped to live
   rows** carrying a predicate for **every verified dialect** (ADR 0069) — both
   `postgresql_where` *and* `sqlite_where`, because a Postgres-only predicate
   silently compiles to a full unique index on SQLite (dev/test) and reinstates
   the trap. Or deactivate-over-delete (how the identity user table keeps
   `email` unique). Shipped tables are already clean; the rule protects
   consumers.

2. **Offline SQL** — `terp migrate upgrade --sql` (`terp.migrations.upgrade_sql`)
   renders the whole upgrade as a DBA-reviewable script on stdout: every
   package's history in the same FK-dependency order `upgrade` applies, under a
   per-package header, **including the `alembic_version_<label>` bookkeeping** so
   a script-applied database still reports current to `status` and the boot
   guard. Nothing connects — the URL supplies only the dialect (the conformance
   test renders against an unreachable host, so success itself proves no
   connection is attempted). **Flat layout only, fail closed:** the per-module
   layout routes DDL through *session* state (`search_path`) that a static
   script cannot carry faithfully; rendering it anyway would land tables in the
   wrong schema. A per-module deployment migrates online. Offline rendering
   targets the **server** dialect: SQLite histories carrying an ALTER cannot
   render offline (Alembic batch mode needs live reflection, surfaced by
   Alembic's own loud `CommandError`) — which is fine, because the DBA workflow
   this serves is a server database.

3. **Recorded posture** (design doc §4.6): synchronous `Session` by design (an
   async variant lands as a *parallel* seam, never a rewrite); one primary
   engine (a read-replica seam is an additive `create_app` parameter);
   UUIDv4 keys (a v7 switch is a generator-default change, not a schema
   change); timestamps use Python-side defaults (a `server_default` is a plain
   migration whenever an external writer needs it); `statement_timeout` rides a
   startup parameter transaction-pooling proxies may not pass — set
   `DB_STATEMENT_TIMEOUT_MS=0` and pin it at the role (documented in
   DEPLOYMENT.md).

## Enforcement

| Layer | Control |
|---|---|
| Build-time | `no_unique_columns_on_soft_delete_models` fails the gate on the trap — including a table that inherits the trait through an app-owned base, and a partial index that predicates only one verified dialect; the both-dialect partial index and deactivate-over-delete pass |
| Runtime | The database's own unique index is the runtime layer — the rule exists because that layer *keeps enforcing against dead rows*; the existing `IntegrityError → ConflictError` mapping keeps the surface a uniform 409 |
| Offline SQL | `upgrade_sql` / `--sql` refuses the per-module layout with a typed `MigrationError` before rendering anything; the conformance suite proves a rendered script contains the DDL + version bookkeeping and that no database file was ever created |

## Consequences

- Consumers with DBA-gated production pipelines are first-class: release
  engineering can review and apply plain SQL, and the boot guard still verifies
  the result.
- The soft-delete rule is the platform's only guard whose "runtime half" is the
  database index itself; the build-time half exists to keep that index from
  becoming a trap.
- Offline rendering of the per-module layout is deliberately unsupported, not
  deferred-by-accident; if a consumer proves the need, the additive path is a
  rendered script that inlines `CREATE SCHEMA` + schema-qualified DDL — a new
  renderer, not a change to the online path.
