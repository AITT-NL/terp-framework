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

## Amendment (2026-11-14): grant-runtime also takes EXECUTE from PUBLIC

PostgreSQL lets `PUBLIC` execute every routine (a function, procedure, aggregate or window
function) from the moment it is created, and a `SECURITY DEFINER` function runs with its
owner's privileges. So a function a migration
made, left as PostgreSQL made it, let the runtime role reach further than the grants above:
the split held for tables and not for routines. A deploy tool that runs `grant-runtime
--owner-role <owner>` as the owner, after every upgrade and every restore, asked for the
revocation. `grant-runtime` now revokes `EXECUTE` from `PUBLIC` in the transaction that
grants, in two parts:

| Routines | How |
|---|---|
| Made later | `ALTER DEFAULT PRIVILEGES [FOR ROLE <owner>] REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC`, the last of `runtime_grant_statements`, written **without** `IN SCHEMA`: a default given per schema adds to the global one and cannot take back what the global one grants (on PostgreSQL 16.15, a function made after a per-schema revocation was still `PUBLIC`'s to execute). `ON FUNCTIONS` covers procedures, aggregates and window functions as well |
| That exist | Each routine of every kind (`prokind` `f`, `p`, `a` or `w`) in the write and read schemas that `PUBLIC` may execute, by name, with the statement PostgreSQL renders from `pg_proc`: `format('REVOKE EXECUTE ON %s %s FROM PUBLIC', …, oid::regprocedure)`, where the keyword is `PROCEDURE` for a procedure and `FUNCTION` for the rest, which `REVOKE` takes for an aggregate and a window function too, under a search_path pinned to `pg_catalog` for the transaction, so every name comes back quoted and schema-qualified, and Python composes none of them into a statement. The schemas are a bound parameter |

What this amendment decides, and why:

1. **Without `--owner-role`, the default is the executing role's own**, exactly as the table
   defaults are: one rule for both, and the advice under Consequences (run it as the
   migration owner, or name that role) now covers both. The by-name half does not depend on
   it: what exists when it runs is revoked, whichever role made it, as long as the running
   role may revoke it (decision 3).
2. **Only what `PUBLIC` may still execute is revoked by name.** A re-run sends no such
   statement, and a routine another role owns that `PUBLIC` can no longer execute is left
   alone, where PostgreSQL would refuse the `REVOKE` outright from a role that holds no
   privilege on it.
3. **The revocation is checked, not trusted.** PostgreSQL lets only a routine's owner, a
   member of its owning role or a superuser revoke what the owner granted; anyone else's
   `REVOKE` revokes nothing and draws only a `WARNING`. So `grant-runtime` reads the catalog
   again, and a routine `PUBLIC` may still execute is a `MigrationError` that names it and
   its owner (the first five, and how many more) and the way out: run it as that owner, or
   make the migration owner its owner. This is the runtime half of the control: the
   statements are the request, and the second read is what the database holds.
4. **One transaction.** The grants, the default, the revocations by name and the check run
   in the transaction `grant-runtime` already opened, so a refusal or a failing statement
   leaves nothing changed.
5. **An extension's functions are left to the extension** (`pg_depend` with
   `deptype = 'e'`), by the by-name half and by the check:
   - its script decides what `PUBLIC` may call, revoking what it guards, and the rest is its
     interface: revoked, citext's own `=` refuses the runtime role a plain comparison
     (`permission denied for function citext_eq`, on 16.15);
   - the role running `grant-runtime` usually cannot revoke them: a superuser creates an
     untrusted extension, and a trusted one the owner creates still gives its member
     functions to the bootstrap superuser. A deploy tool that creates its allowlisted
     extensions as the superuser puts them in `public`, one of `grant-runtime`'s schemas
     under both layouts, so sweeping them would have every such app refused by decision 3;
   - an `ALTER EXTENSION … UPDATE` whose script recreates a function gives it that script's
     privileges, not these.

   The owner's default reaches an extension's functions only where the owner is itself a
   superuser that creates the extension: they then come without `PUBLIC`'s `EXECUTE`, like
   any routine it makes.
6. **A trigger keeps firing.** PostgreSQL checks `EXECUTE` on a trigger's function when the
   trigger is created, not each time it fires (on 16.15, with `EXECUTE` revoked from
   `PUBLIC`, a trigger function still fired when a role without `EXECUTE` inserted into its
   table). What the trigger function calls is checked as usual, as the role whose statement
   fired it, so a call it makes to another of the app's functions is refused like any other.
   The audit capability's append-only trigger function (ADR 0076) calls none, and is revoked
   like any other.
7. **Aggregates and window functions are revoked by name too.** The default covers the ones
   made later, so the two halves agree on every kind. And an aggregate is a way round a
   revoked function: PostgreSQL checks `EXECUTE` on an aggregate's state and final functions
   against the aggregate's owner, not its caller, so revoking a `SECURITY DEFINER` state
   function alone leaves it reachable through an aggregate made before `grant-runtime` ran
   (on 16.15 the runtime role read a table outside its grants that way).

**What this leaves open.**

- **An app whose statements reach a function of its own** needs that function granted to
  the runtime role (`GRANT EXECUTE ON FUNCTION … TO <runtime role>`), wherever the call
  sits: in the statement itself, in a view, in a column's default, a generated column, an
  index expression, a check constraint or a row-level security policy, or in a trigger
  function. On 16.15 each of those is refused under a role without `EXECUTE`, with
  `permission denied for function …`. This release does not grant it; a later change takes
  it up, and the PostgreSQL lane and a test run show which apps that is. A grant made by
  hand survives a re-run, because `grant-runtime` revokes only what `PUBLIC` holds.

| Layer | Control |
|---|---|
| Database (fail-closed) | Through `PUBLIC`, the runtime role may execute none of the routines that were in the app's schemas when `grant-runtime` ran (an extension's aside), nor any the owner makes after it; triggers fire regardless |
| Runtime | `grant-runtime` reads the catalog again after revoking, and refuses a routine `PUBLIC` may still execute, changing nothing |
| CI | The PostgreSQL lane: a `SECURITY DEFINER` function, a procedure, an aggregate over a `SECURITY DEFINER` state function and a window function made before refuse the runtime role, and the audit capability's trigger function is no longer `PUBLIC`'s; ones made after refuse it, and the default holds in a schema `grant-runtime` never named; a trigger still fires and the grants still hold; a second run changes no privilege, revokes nothing and keeps a grant made by hand; a routine the running role cannot revoke is refused, leaving the routine it could revoke, the default and the table grants as they were; an extension's functions stay `PUBLIC`'s |

## Amendment (2026-11-14): check-roles holds an external database's two roles

Where Terp provisions the database, it makes both roles. Where an operator brings one, a
managed or external PostgreSQL, Terp creates no role, and the split this ADR draws holds only
if the two roles it is given are shaped as the ADR says. A deploy tool checks them before it
backs anything up or migrates anything, and asked for the command it runs:
`terp migrate check-roles <runtime role> --owner-role <owner role>`, as the owner (the owner's
connection in `DATABASE_URL`), in the release's own image. It reads both roles by name from
the catalog, so it needs no runtime connection. It changes nothing: it sets its transaction
`READ ONLY`, so PostgreSQL refuses any write in it, and never commits it.

It exits 0 with one line naming the roles and the schemas it read; 3 with every failure, one
per line, each naming what to change; and 1 with one line when it could not check, such as a
connection that fails. argparse's usage error stays 2. Every line it prints begins
`check-roles: `. A deploy tool runs it through a container engine, which exits non-zero for
failures of its own and writes its own lines to standard error, so the mark and the exit tell
the command's answer from the engine's: 3 is an exit no engine gives for a failure of its own,
and an exit 1 carries a marked line only when the command itself said why. Nothing it prints is
a value of the connection: a connection that fails is one line too, without the driver's
message, which names the host, the port and the user.
Role names are held to `grant-runtime`'s pattern and refused before connecting. The pattern is
now matched against the whole name, by both commands: a pattern's `$` also matches before a
trailing newline, which let `"terp_rt\n"` through to the server. A database that is not
PostgreSQL is refused as `grant-runtime` refuses it.

The app's schemas are the ones `grant-runtime` grants on under the layout, and `public`
always. A schema the database does not hold yet is not read, and is named as not created yet:
the check runs before a fresh database's first migration, when the owner has created none of
the package schemas, and `has_schema_privilege` raises on a schema that does not exist.

| Check | Why |
|---|---|
| Both roles exist | Every other check reads them |
| The runtime role is not a superuser | A superuser passes every privilege check, so the split is void |
| It has none of `CREATEROLE`, `CREATEDB`, `REPLICATION`, `BYPASSRLS` | Decision 1 |
| It is not a member of the owner role, directly or through another role (`pg_has_role(…, 'MEMBER')`) | A membership without `INHERIT` reads false in `has_schema_privilege`, yet `SET ROLE` gives the runtime role the owner's rights: on 16.15, a runtime role linked to the owner through a `NOINHERIT` role read false for `CREATE` in the owner's schema, and true after `SET ROLE`. The same role named for both reads as its own member, and is named as one role for both |
| It owns no relation in the app's schemas, and is a member of no role that owns one there | A relation's owner may alter or drop it. Matching `pg_has_role` against `relowner` rather than equality also finds a table a third role owns that the runtime role belongs to |
| It may not `CREATE` in the database (`has_database_privilege`) | It could create schemas, one a package has not created yet among them |
| It may not `CREATE` in any of the app's schemas (`has_schema_privilege`) | That is DDL; before PostgreSQL 15 everyone may `CREATE` in `public`, which this finds |
| It cannot act as the owner of `public` | Decision 2 |
| The owner role owns each of the app's schemas, `public` aside (`pg_namespace.nspowner`) | The migrations run as the owner, and `grant-runtime`'s defaults and revocations are the owner's |

What this amendment decides, and why:

1. **Every attribute beside superuser is refused too.** An app's connection needs none of them,
   and each widens what a compromised app process reaches: `REPLICATION` streams every
   database's changes off the server, `BYPASSRLS` passes every row-level security policy,
   `CREATEROLE` creates roles and, before PostgreSQL 16, could grant itself any non-superuser
   role, the owner included, and `CREATEDB` creates databases on the server.
2. **`public` may have any owner the runtime role cannot act as.** It holds the version tables
   and the window record under `per-module`, and every table under `flat`, and a schema's
   owner may drop every table in it, whoever owns the tables. So the runtime role must not own
   `public` or be a member of its owner. Who owns it otherwise varies: `pg_database_owner` from
   PostgreSQL 15 (the owner role, while it owns the database), the bootstrap superuser before
   that, a provider's administrator role on a managed service. Requiring the owner role would
   refuse most external databases as they come, for nothing the rule above does not give, so
   `public` is the one schema the ownership check sets aside.
3. **A failure that only follows from another is not listed twice.** A superuser passes every
   privilege check, so for one only its attributes are reported. A member of the owner role
   holds the owner's rights, so for one `CREATE` in the database and the schemas, the owner
   of `public` and the owner's own relations are not checked. The line naming the cause
   fails the check, and a run once it is fixed lists what remains.

| Layer | Control |
|---|---|
| Runtime | `check-roles` exits 3 with every failure and what to change, each line marked `check-roles: `; a deploy reports it as its refusal |
| CI | The PostgreSQL lane: each fault alone, named with its remedy; several at once; a pair `grant-runtime` shaped passes under both layouts; nothing changes, and the transaction is read-only before the first catalog read; the command line's exit codes, the refusal of a name before connecting, and no password in what it prints |
