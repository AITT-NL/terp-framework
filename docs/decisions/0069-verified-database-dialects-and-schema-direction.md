# 0069 - Verified database dialects and the per-module schema direction

- **Status:** Accepted
- **Date:** 2026-07-05
- **Context phase:** Post-Tier-1 hardening — making the implicit database support
  matrix explicit and testable
- **Supersedes/relates:** [ADR 0027](0027-packaged-migrations-per-package-histories.md)
  (packaged migrations), [ADR 0011](0011-model-traits-vs-control-plane-policy.md)
  (control-plane owns the *how*), [ADR 0062](0062-production-deployment-profile.md)
  (the deployment profile ships PostgreSQL)

---

## Context

Terp's database support was implicit. SQLite is the dev/test engine (the entire
gate runs on it) and PostgreSQL is the deployment path (the Docker workbench,
the production profile, and every dialect-specific optimization target it) — but
nothing *enforced* that matrix. Production boot refused SQLite and nothing else,
so a deployment could point `DATABASE_URL` at MySQL and ship on a path no test
had ever exercised. Meanwhile the SQLite-only gate is known to mask real
differences: SQLite does not enforce `VARCHAR` length, returns naive datetimes,
and needs Alembic batch mode where PostgreSQL alters natively.

Separately, per-module **schema separation** (physically namespacing each
module's tables into its own PostgreSQL schema, as groundwork for per-schema
`GRANT`s) needs a design direction — and any candidate design lives or dies on
exactly these dialect differences, so the two decisions are coupled.

## Decision

1. **The support matrix is explicit: SQLite for dev/test, PostgreSQL for
   production.** In production, `Settings` now fails construction for any
   non-PostgreSQL server dialect unless the deployment sets the new
   `DB_ALLOW_UNVERIFIED_DIALECT=true` acknowledgement (SQLite stays refused
   unconditionally). Nothing is *removed*: SQLAlchemy-supported dialects still
   work everywhere else and behind the acknowledgement — the control makes the
   unverified-path choice loud and deliberate instead of silent.
2. **A PostgreSQL conformance lane runs in CI.** A new `postgres-lane` job runs
   the migrations-conformance suite against a real `postgres:17` service: the
   `db_url` fixture is parametrized over `sqlite` and `postgresql`, each test
   creating (and force-dropping) its own scratch database. Locally the lane
   skips unless `TERP_TEST_POSTGRES_URL` is set, so the offline gate is
   unchanged. This converts "PostgreSQL is supported" from an aspiration into a
   failing test — upgrade/downgrade of every packaged history, the autogenerate
   drift check, stamp/heads/CLI, and the pending-migrations boot guard are all
   proven on the verified dialect.
3. **Per-module schema separation will use the `search_path` recipe, not
   `schema_translate_map`.** The design investigation (recorded here so the
   rejected path stays rejected):
   - *Rejected:* logical schema tokens on `BaseTable` +
     `schema_translate_map`. The Alembic cookbook states verbatim that Alembic
     "lacks adequate support for this feature"; its multi-tenancy recipe
     requires metadata with `schema=None` and `include_schemas` off. The
     SQLAlchemy docs confirm the map never affects `text()` / raw SQL. And
     schema tokens on models would break every bare
     `SQLModel.metadata.create_all(...)` on SQLite (~30 test sites plus any
     consumer-built engine), since SQLite parses a schema prefix as an ATTACH
     database name.
   - *Chosen direction:* metadata stays schema-free forever. The `per-module`
     layout becomes a deployment concern — a control-plane `DatabaseConfig`
     knob (the ADR 0011-reserved *how*), applied at migration time
     (`CREATE SCHEMA IF NOT EXISTS` + `SET search_path` per package history,
     the documented Alembic recipe) and at connection time (the engine's
     `search_path`), fail-closed to PostgreSQL. Implementation is a follow-up
     slice with its own ADR; this lane is its hard prerequisite, because the
     recipe's fiddly corner (autogenerate/drift-check behavior under
     `search_path`) must stay pinned by tests.

## Enforcement

| Layer | Control |
|---|---|
| Runtime (fail-closed) | Production `Settings` refuses an unverified server dialect without `DB_ALLOW_UNVERIFIED_DIALECT=true`; SQLite refused unconditionally |
| Build-time | `test_kernel_coverage` guardrail cases (rejection + acknowledgement + SQLite-stays-refused) |
| CI | The `postgres-lane` job — the verified-dialect claim is executed, not asserted |
| Governed opt-out | `DB_ALLOW_UNVERIFIED_DIALECT` itself: explicit, named, per-deployment |

Generated projects inherit the runtime guardrail automatically (same `Settings`)
and already exercise PostgreSQL end-to-end in their own CI (the compose
conformance job boots the PG workbench), so no template change is needed.

## Consequences

- The known SQLite blind spots (VARCHAR bounds, timezone-aware datetimes,
  native ALTER) are now covered where they matter most — the migration
  subsystem — and the lane is the natural home for future dialect-sensitive
  regression tests (e.g. `SKIP LOCKED` claim paths).
- `psycopg[binary]` joins the dev dependency group; tests skip without a server,
  so local runs need no PostgreSQL.
- Adding another *verified* dialect later has a defined bar: extend the lane's
  fixture and CI matrix until the conformance suite is green, then widen the
  guardrail — the acknowledgement knob is never the long-term answer for a
  dialect we claim to support.
- Tier 2 of the schema work (per-module database roles + `GRANT`s — the layer
  that makes the *database* refuse cross-module access) remains deliberately
  undecided; it carries real operational cost and gets its own ADR after the
  `per-module` layout ships.
