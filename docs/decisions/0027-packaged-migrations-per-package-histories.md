# 0027 - Packaged migrations: independent per-package Alembic histories (Phase 7)

- **Status:** Accepted
- **Date:** 2026-06-26
- **Context phase:** Phase 7 (migrations across packaged core + modules, design §4.6 / §13)
- **Relates:** [ADR 0001](0001-terp-namespace-and-kernel-scope.md) (the `terp.core`
  layer-0 boundary — the kernel must not depend on Alembic),
  [ADR 0007](0007-audit-auto-emit-and-the-audit-seam.md) /
  [ADR 0015](0015-runtime-write-guarded-session.md) (the two-layer, fail-closed
  discipline this control follows), [ADR 0013](0013-users-capability-and-identity-boundary.md)
  (identity is a *library* capability with no router entry point — which is why
  migrations are discovered through a **dedicated** entry-point group, not the router
  group), [ADR 0024](0024-health-endpoints-and-pool-config.md) (the production
  fail-fast boot checks this guard joins).

---

## Context

Terp could create a schema (`SQLModel.metadata.create_all`) but had **no way to
evolve a deployed one** — the single biggest gap to production-readiness (design §14
rates packaged-migration complexity *High*, and §13 makes it the dedicated,
design-first Phase 7). The problem is genuinely distributed-ownership: the schema a
consumer runs is the union of several **independently-versioned** packages — the
table-owning capabilities (`audit`, `identity`, `access`) plus the app's own modules
(`notes`, `tasks`, `projects`, …) — and when the platform ships a new version, the
consumer must apply *that package's* schema change for the app to keep working.

Design §4.6 sketched "one Alembic graph with multiple `version_locations` + **branch
labels**." Multiple branches in one history is the part of Alembic that most often
bites teams (merge migrations, `heads` vs `head`, autogenerate picking up another
package's tables) — the wrong default for a platform whose whole thesis is removing
footguns. Two consumer concerns drove the refinement: *how are conflicts avoided*,
and *how is "the consumer must migrate for a new version" actually guaranteed*.

## Decision

Adopt **Alembic** (the SQLModel-native, battle-tested choice — no serious
competitor for autogenerate against SQLModel metadata), but as **independent,
linear per-package histories** rather than one shared multi-branch graph.

### 1. One linear history per table-owning package, isolated by its own version table

Each table-owning package owns a plain, linear Alembic history inside its package
(`<pkg>/migrations/versions/*.py`) with its **own** `alembic_version_<label>` table.
`terp migrate upgrade` discovers every package and runs each one's `upgrade head`;
`downgrade` reverses the order. There is no shared graph, so there are **no merge
migrations and no multiple-heads to reason about**.

- **Conflicts are eliminated by construction.** No two packages share a history or a
  version table, and Terp's capabilities are deliberately **FK-less leaves**
  (`audit.actor_id`, `access.subject_id` carry no FK to the higher-layer `User`), so
  there are no cross-package ordering edges to conflict over. The package order is a
  determinism convenience, never a correctness constraint.
- **Autogenerate is scoped per package.** The shared `env.py` limits
  `include_name` / `include_object` to the tables a package *owns* (a table whose
  mapped class lives under the package's import path), so `terp migrate make audit`
  proposes only `audit_event`, never another package's tables.

### 2. A pure discovery seam in the kernel; the Alembic integration outside it

- **`terp.core.migrations`** (new public seam, **no Alembic import**) resolves each
  package's history: capabilities via a dedicated `terp.migrations` entry-point group
  (so even a *library* cap like `identity`, which has no router entry point,
  participates), app modules via the filesystem (`app/modules/<name>/migrations`). It
  is a side-effect-free path walk safe to call from Alembic's `env.py` and inside the
  layer-0 boundary. A duplicate version label fails closed.
- **`terp-migrations`** (new package, depends on `terp-core` + `alembic`) holds all
  Alembic integration: one Terp-owned `env.py` (parameterized per run by the package's
  import path + version table), the per-package orchestration (`upgrade` / `downgrade`
  / `make` / `migration_status`), and the boot guard. **Consumers never hand-write
  `env.py`** — Terp builds the config from discovery, so "install a capability → its
  migrations just run" holds (the Phase-2 gate). The kernel never imports this package,
  keeping Alembic out of layer 0.
- **`terp migrate`** is exposed on the `terp` CLI (delegating to `terp-migrations`,
  lazily imported so `terp inspect` / `terp guide` never load Alembic) and as a
  standalone `terp-migrate` script.

### 3. Two-layer guarantee that the consumer migrated (the second concern)

- **Runtime control:** `terp.migrations.assert_migrations_current(engine)` raises a
  typed `PendingMigrationsError` when any package's database history is behind its
  code head. `create_app(..., migration_check=…)` is the seam that runs it at boot, so
  an app **refuses to serve a stale schema** — a deploy that skipped
  `terp migrate upgrade` fails loudly, not silently. The seam is opt-in and injected
  (the kernel never imports the migration subsystem); the example app wires it outside
  local development.
- **Build-time control:** the Phase-7 **conformance test** (install capability →
  upgrade → downgrade across all six packages and their independent version tables),
  plus a **drift test** asserting autogenerate finds *no* changes after upgrade — the
  committed migrations exactly match the models, so a changed model with no
  regenerated migration is caught in the gate, not in production.

### 4. Coverage / arch treatment

Generated Alembic artifacts (the shared `env.py` / `script.py.mako` and every
package's revision scripts) are excluded from the 100% line-coverage gate via
`[tool.coverage.run] omit`, mirroring the arch harness's existing `migrations` skip
(`_SKIP_DIRS`) — they are generated DDL, exercised end-to-end by the conformance test,
not framework logic. The orchestration / guard / runtime logic in `terp.migrations`
**is** measured (100%).

## Consequences

- The critical production gap is closed: a deployed schema can evolve, the platform
  ships tested migrations for its capabilities, and the consumer applies them with one
  `terp migrate upgrade` — enforced at boot.
- This **refines design §4.6**: "independent per-package histories" supersede "branch
  labels" as the merge mechanism (same outcome — each package owns its tree — with a
  far gentler failure surface). §4.6 / §13 are updated to match.
- Three capabilities gain a `terp.migrations` entry point; the six table-owning
  packages ship an initial revision. Escape-hatch budgets stay `{}` (migration dirs
  are arch-exempt).
- **Deferred (tracked):** offline `--sql` migration output for DBA review; a
  `tables_have_migrations` build rule (every table-owning package ships a history);
  the durable event-outbox tables will slot in as their own package history when built.

## Post-review hardening (2026-06-26)

A pre-release red-team (real wheels + a clean non-editable venv install, Dockerized
Postgres, scratch consumer apps with cross-module foreign keys) confirmed the
packaging / discovery / fidelity core works for a real install and that the
SQLite-authored migrations apply on Postgres with **no** drift. It also surfaced
consumer-facing gaps, now fixed — each a fail-closed runtime change **and** a build-time
test, with the per-package-independent-history design unchanged:

- **Cross-package / cross-module foreign keys work end to end.** Autogenerate imports
  *every* discovered package's models into the shared metadata (so an FK target — a
  sibling module's table, or `identity_user` — resolves) while `include_name` /
  `include_object` still scope the *emitted* tables to the package being migrated; and
  `upgrade` is **topologically ordered by FK dependencies**, so a referenced table is
  created before the table that references it regardless of label ordering (`downgrade`
  reverses it). A cross-package FK *cycle* cannot be linearised and fails closed.
- **Homeless tables fail closed at `make`.** A bare association `Table` (no mapped
  class) wired into an owned table by a foreign key — which every package's scoped
  autogenerate would silently skip — now raises at `terp migrate make`, with
  `unmapped_tables` exposed for a consumer's own checks. Unrelated bare tables are
  ignored, so the check never false-positives.
- **Batch mode is dialect-gated.** `render_as_batch` is SQLite-only (it works around
  SQLite's `ALTER` limits); on Postgres / MySQL migrations emit direct `ALTER` instead
  of `op.batch_alter_table`, removing a latent destructive table-recreate footgun.
- **Brownfield adoption — `terp migrate stamp`.** Baselines an existing database (e.g.
  built by `create_all`) at head without running DDL, so a consumer adopts the
  histories without dropping data.
- **Within-package divergence — `terp migrate heads` / `merge`.** Two developers
  branching one package produce multiple heads (cross-*package* branching is still
  impossible); these surface and resolve it without a hand-built Alembic config.
- **Safer `downgrade`.** The all-package form accepts only globally-meaningful targets
  (`base` / relative `-N`); a package-specific revision requires `--label` (one
  package), so a concrete hash can never be mis-applied to every package.
- **The boot guard can cover app modules.** `assert_migrations_current` already accepted
  an `app_root`; the example now passes it, so a stale *app-module* schema (not only a
  capability's) fails boot — asserted by a build-time test.
- **Reusable drift check + homeless-table helper.** `assert_migrations_match_models`
  lets a consumer's tests assert migrations match models (a model change with no
  migration fails CI, not production); `unowned_tables` surfaces a table owned by no
  package (e.g. a bare association `Table`).

**Documented operational guidance (not code):** run `terp migrate upgrade` once per
deploy (a release job), not on every replica — it takes no lock, while the read-only
boot guard is safe per replica; the migration engine is built from `DATABASE_URL`, so
URL-expressible options (e.g. `sslmode`) apply, while non-URL `connect_args` and
non-public schemas remain a known limitation; review autogenerated migrations before
applying (a `NOT NULL` add-column needs a `server_default` / backfill on a populated
table); prefer SQLModel link-model classes over bare association `Table`s so ownership
sees them.

- Gate: **green at 100% line coverage.**
