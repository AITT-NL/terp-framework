# `backend/no_destructive_migrations`

**Destructive migration steps require a reason-bearing marker**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/no_destructive_migrations.json`.

## Why this rule exists

A deploy migrates while the previous release still serves, and a rollback runs that release against the migrated schema, so an upgrade has two audiences its author's empty test database never shows: the rows production already holds, and the release still running. Five kinds of step fail one of them, whether spelled as a schema operation, on a batch block, through an alias, or smuggled into a raw statement. A step counts wherever the upgrade runs it: in a function of the same revision that the upgrade calls, under a name it is imported as, looked up by a literal name, as one of several statements in one raw text, and in every revision file the migration tool loads, whatever the file is named. A drop (of a table or a column, or a statement that truncates or deletes rows) destroys data nothing brings back. A rename of a table or a column breaks the running release, which reads the old name. A type change can truncate or refuse existing values. Tightening an existing column to NOT NULL fails on the first row that holds NULL. And a constraint added to an existing table (unique, check, foreign key, primary key, a unique index, or the validation of one first added without checking the existing rows) fails on the first row that breaks it. Each such step is one finding, and its message says what to do instead: expand (add the new name or column beside the old one), backfill the rows outside the upgrade, and contract (drop, tighten or constrain) in a later release. The contract step is the destructive one; a reviewed one is justified through the standard governed escape hatch, a justified marker on (or immediately above) the operation, counted against the app's budget ratchet, so every accepted risk is explicit, reviewable, greppable, and ratcheted like any other opt-out. Two shapes meet no row that can break them and are not findings: a step on a table the same upgrade creates, and a unique, foreign-key or unique-index constraint on columns the same upgrade adds nullable with no default. Not being a finding does not make a step an expand step: whether the previous release keeps working after an upgrade is a separate question this rule does not answer.

## How Terp realises this

In every revision file Alembic loads from versions/ (every *.py there but __init__.py and an editor's .# lock file), in upgrade() and in every top-level function of the revision it calls by name, transitively (a top-level upgrade = <name> names the upgrade), on op, a batch_alter_table handle or any alias, imported by name from alembic.op, or looked up by getattr with a literal name: drop_table / drop_column; rename_table and alter_column(new_column_name=...); alter_column(type_=...); alter_column(nullable=False) unless it restates existing_nullable=False or the table is created in the same upgrade(); create_unique_constraint / create_check_constraint / create_foreign_key / create_primary_key / create_exclude_constraint / create_index(unique=True) on a table that upgrade() does not create, a unique, foreign-key or unique-index constraint on columns that upgrade() adds nullable with no server_default excepted; and execute(...) / exec_driver_sql(...) of a statement written as a literal, an f-string or a + of strings, read one statement at a time, split at each ; outside a quoted string or identifier, a dollar-quoted body and a comment: DROP TABLE / DROP COLUMN / DROP SCHEMA / TRUNCATE / DELETE FROM / ALTER TABLE ... DROP (DROP NOT NULL excepted), ALTER TABLE ... RENAME (a constraint rename excepted) / RENAME TABLE, ALTER COLUMN ... TYPE, SET NOT NULL, ADD [CONSTRAINT] UNIQUE / PRIMARY KEY / CHECK / FOREIGN KEY / EXCLUDE (a check or a foreign key added NOT VALID excepted), CREATE UNIQUE INDEX and VALIDATE CONSTRAINT. Each operation is one finding, with the message for its kind; the standard # arch-allow-no-destructive-migrations marker (budgeted) justifies a reviewed one. The pre-0.6.0 file-level terp-allow-destructive-migration waiver is retired.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-no-destructive-migrations: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## What the check is not required to catch

A check precise enough to have no false positives has limits. This
rule's limits are recorded as data (its corpus's `RESIDUALS.json`), so
where detection ends is a statement rather than a guess:

- a statement the source does not spell out (a variable, a value a helper returns, a query-builder construct such as `op.execute(notes.delete())`, a file read at run time) is not required to be read: only a statement written as a literal, an f-string or a concatenation of strings is
- an operation whose name is computed (`getattr(op, name)(...)` with a name that is not a literal, source text run through `exec`) is not required to be read: an operation is read under its own name, under a name the revision imports it as at its top level, or through `getattr` with a literal name
- a step the upgrade reaches other than by calling a top-level function of the same revision by its name (a helper imported from another module, a callable held in a variable, a method, a function passed as a value and called through it) is not required to be followed
- an upgrade entry point bound to anything but a top-level function of the revision, directly or through a chain of top-level names (`upgrade = make_upgrade()`), is not required to be resolved
- rows deleted through an object-relational session rather than by a statement or a schema operation (`session.delete(row)`, `session.query(Note).delete()`) are not required to be read as a drop
- a revision file in a subdirectory of the versions directory, which the migration tool loads only when it is configured to search recursively, is not required to be read
- a unique, foreign-key or unique-index constraint on a column the same upgrade adds nullable is not required to be reported when that upgrade fills the column before adding the constraint, which is the one order in which the existing rows can break it
- a constraint written inline in a raw column addition (`ADD COLUMN slug text UNIQUE DEFAULT 'x'`, `ADD COLUMN rank int NOT NULL`) is not required to be read as a step the existing rows can break

**These are not exemptions.** The rule governs those forms exactly as it
governs any other — a checker is simply not required to find them, so
review is the control there. The list only shrinks: closing one means
adding the corpus case that contracts it.

## Enforcement

- Checked while the app runs? No — this is a property of the written source only; the build-time check is the control, by recorded decision.
- `build-time`: `terp.arch` — `check_no_destructive_migrations`
