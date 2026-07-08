# 0071 - Runtime role privilege split (per-schema GRANTs)

- **Status:** Accepted
- **Date:** 2026-07-05
- **Context phase:** Tier 2 of the schema-separation work — the layer where the
  *database itself* refuses out-of-contract access
- **Supersedes/relates:** [ADR 0070](0070-per-module-schema-layout.md) (the
  per-module layout this grants over), [ADR 0069](0069-verified-database-dialects-and-schema-direction.md)
  (PostgreSQL as the verified dialect), [ADR 0007](0007-audit-auto-emit-and-the-audit-seam.md) /
  [ADR 0045](0045-durable-outbox.md) (single-session atomicity this deliberately preserves)

---

## Decision

Deployments split database privileges into two PostgreSQL roles:

- the **owner** role (whatever `terp migrate` connects as today): owns the
  schemas and tables, runs DDL — migrations, `adopt-schemas`, and this grant
  command itself;
- a **runtime** login role the app's `DATABASE_URL` uses: exactly the DML the
  audited service layer needs, and nothing else.

`terp migrate grant-runtime <role>` shapes the runtime role's privileges
(idempotent, one transaction). Terp never creates the login or handles its
password — the operator provisions credentials; the command only grants:

| Surface | Privileges |
|---|---|
| Write schemas | `SELECT, INSERT, UPDATE, DELETE` on all tables; `USAGE, SELECT` on sequences; matching `ALTER DEFAULT PRIVILEGES` so tables created by future `terp migrate upgrade` runs are covered automatically |
| Read schemas | `SELECT` only (+ default privileges) |
| Database | `CONNECT` |
| Never | `CREATE`, ownership, any DDL |

**Layout-aware.** Under `per-module` (ADR 0070) the package schemas are the
write surface and **`public` becomes read-only**: the boot guard can still read
`alembic_version_*`, but the app can no longer tamper with migration state —
a concrete integrity win over the flat layout, where `public` must stay
writable because every table lives there.

## What one decision deliberately rejects

**Per-request / per-module runtime roles** (a `SET ROLE` per module, or one
connection pool per module) are rejected, not deferred. Terp's core guarantees
ride *one* session per request unit: the audit row (ADR 0007) and the outbox
row (ADR 0045) commit atomically with the business write. Splitting sessions
per module would either break that atomicity or force distributed transactions
— trading the platform's strongest invariant for marginal in-process
containment. The module-level boundary stays code-enforced
(`no_cross_module_imports`, service-only writes); the *process*-level boundary
is now database-enforced by this role split.

**Corollary — stated so it is never misread:** because one runtime role holds
DML on every write schema, the database does **not** block module-to-module
DML (the app's login can `INSERT` into another package's schema). What the
database blocks under this split is DDL (create/drop/alter), ownership, and —
under `per-module` — every write to `public`, including migration state. The
live conformance test pins both sides: the refusals *and* the deliberately
allowed cross-schema DML.

## Enforcement

| Layer | Control |
|---|---|
| Database (fail-closed) | The runtime role physically lacks DDL and any write to the read surface — PostgreSQL refuses `CREATE`/`DROP`/`ALTER` everywhere and, under `per-module`, every write to `public` (migration state included). Module-to-module DML is *not* database-blocked (see the corollary above) |
| Runtime | `grant-runtime` refuses non-PostgreSQL dialects and non-identifier role names (`MigrationError`) before touching the database |
| CI | The PostgreSQL lane proves the boundary live: the granted role performs the full DML surface + reads migration state + (pinned as allowed) writes another package's schema, then `CREATE TABLE` / `DROP TABLE` / `ALTER TABLE` / `DELETE FROM alembic_version_*` each raise `insufficient_privilege` |
| Ops shape | Grants run in one transaction; `ALTER DEFAULT PRIVILEGES` (scoped with `FOR ROLE` via `--owner-role` when the grantor is not the migration owner) keeps future tables covered so an upgrade never strands the runtime |

## Consequences

- The deployment recipe becomes: migrate/adopt as the owner role → `terp
  migrate grant-runtime app_rt` → point the app's `DATABASE_URL` at the runtime
  login. Compose/production profiles can adopt this incrementally; nothing
  changes for deployments that keep a single role.
- `ALTER DEFAULT PRIVILEGES` applies to objects created by the role named in
  the statement. Run `grant-runtime` as the migration owner, or pass
  `--owner-role <role>` so the defaults are scoped with `FOR ROLE` to the role
  that actually runs `terp migrate` — otherwise tables created by future
  upgrades would not be covered and the runtime would be stranded. The command
  is idempotent and cheap to re-run after any upgrade regardless.
- A compromised app process is now bounded by the database: it can read/write
  rows (subject to the app-layer guards) but cannot alter schema, drop tables,
  or rewrite migration history.
- Row-level security (per-tenant RLS) remains a possible Tier 3 — a separate
  decision with its own cost/benefit.
