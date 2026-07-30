# 0090 — A table has exactly one owning migration history

Status: accepted

## Context

Terp gives every table-owning package — a capability or an app module — its own
**independent, linear** Alembic history with its own `alembic_version_<label>` table
([ADR 0027](0027-packaged-migrations-per-package-histories.md)). There is no shared revision graph
and no cross-package merge. Two consequences make that work: each package's autogenerate
is *scoped* to the tables its own models declare (`scoped_filters` in
`terp.migrations._runtime`), and `terp migrate upgrade` orders the histories by foreign-key
dependency so a referenced table is created before the table referencing it.

Moving a model from one module to another is an ordinary refactor. An agent doing it will
move the class, run `terp migrate make` for both modules, run the gate, and see green.

We ran it. Twice, with real databases.

**Probe 1** — move `Note` from module `notes` to module `tasks`, keeping
`__tablename__ = "notes_note"`, with a row in the table:

| step | result |
|---|---|
| `terp migrate make notes` (the losing module) | **empty migration** — no `drop_table` |
| `terp migrate make tasks` (the gaining module) | **empty migration** — no `create_table` |
| upgrade the existing database | OK |
| upgrade a **fresh** database | OK, `notes_note` present |

No DDL is generated at all. The losing package no longer owns the table, so its scoped
autogenerate cannot see it to propose a drop; the gaining package diffs against a database
where the table already exists and matches its model, so it proposes no create. Model
ownership and history ownership have silently diverged, and everything is green.

**Probe 2** — the same move `zeta` → `alpha` (uphill in label order), followed by the next
ordinary schema change: add a nullable column.

```
zeta/…_create_note.py : op.create_table('notes_note', …)
alpha/…_add_colour.py : batch_op.add_column(sa.Column('colour', …))

existing upgrade: OK
fresh upgrade FAILED: (sqlite3.OperationalError) no such table: notes_note
```

The `add_column` is authored into `alpha`'s history. There is no foreign key between the
two modules, so nothing constrains the order and it falls back to label sort — `alpha`
runs before `zeta`. Probe 1 had only passed by alphabetical luck.

This is the worst failure shape we have found in the platform:

- The long-lived database upgrades cleanly, so CI, staging and production stay green.
- Only a **fresh** install breaks — a new environment, a new developer, a restore, a
  disaster-recovery rebuild.
- The breakage lands months after the commit that caused it, and `git blame` points at an
  innocent "add a column" migration rather than at the move.

No existing control catches it. The destructive-migration rule is irrelevant (nothing is
dropped). The drift guard is satisfied (each package matches its own models). There is no
table-name-prefix rule, so nothing forces the physical table to be renamed on a move.

## Decision

**A table's owning package — the one whose models declare it — must be the package whose
history creates it.** A split is refused, fail closed, at two points:

- **authoring time** — `terp migrate make` refuses before writing a revision, so the
  poison migration is never created; and
- **build time** — `assert_migrations_match_models`, which an app's own gate runs, refuses
  before it looks for drift.

The check (`misowned_tables` / `assert_no_split_table_ownership`) is a static scan: for each
tree, the tables its models own, against the tables its revision files literally
`create_table(...)` inside `upgrade()`. It needs no database, which is why it can run in
both places. It is deliberately conservative — a table owned but created by *nobody* is the
normal state right before a `make` authors it, and a table created under one name and later
renamed has no literal create under its current name, so neither is reported. It only ever
fires on an exact, statically provable foreign creator.

The sanctioned way to move a table is **expand/contract**, documented in
`terp guide migrations`: the new module gets its own table with its own `__tablename__`,
a migration copies the rows, and a *later* release drops the old table.

## Consequences

The refactor that used to be silent now fails at the commit that causes it, with a message
naming both remedies (move the model back, or expand/contract).

**The drop stays human-reviewed.** Step three of expand/contract still requires
`# arch-allow-no-destructive-migrations: <reason>` and a reviewer, and an agent may never
spend that budget autonomously. We considered relaxing it for the "obviously safe" retire
of a copied table and rejected it: whether the copy really completed and whether anything
still reads the old table are facts about a running deployment, not about the source tree.
Dropping a populated table is a genuine, irreversible risk, and requiring sign-off exactly
there is the design working rather than failing.

The check costs one AST parse per revision file per `make` and per gate run, which is
negligible next to the Alembic work already happening.

**A move that carries no data has a cheaper answer** than expand/contract: move the class
back and rename the module. The guide says so, so the ratchet does not push an author into
a three-release dance for a table with nothing in it.
