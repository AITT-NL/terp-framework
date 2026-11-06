# `backend/expand_revisions_only_expand`

**A migration revision that declares itself expand-only holds only expand operations**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/expand_revisions_only_expand.json`.

## Why this rule exists

A revision may declare that the previous release keeps working on the schema it leaves. That promise is what lets a release be rolled back by starting the previous release again on the same database, instead of restoring a backup and losing every write made since. It holds only for a closed list of operations: creating a table together with what is its own (its keys, constraints and indexes, unique ones included, a foreign key from it only with a cascading or nulling delete action and never onto a table whose rows are soft-deleted rather than deleted) and seeding the rows of that new table; adding a column to an existing table that is nullable, has a default or is generated, and declares no uniqueness, no check and at most a nulling foreign key on that nullable column; and adding an index that is not unique. Everything else breaks it: any drop, rename, type change or tightening; a uniqueness or check constraint, a unique index or a primary key change on an existing table; any raw statement or data write to an existing table; rebuilding a table; and a revision that merges two branches. A declaration the operations do not support is refused before the release ships, and refused again while the migration runs, before the operation executes. There is no opt-out: a revision that needs an operation off the list declares that it is not expand-only, which costs only the restore-free rollback of its own release.

## How Terp realises this

A revision file whose module level declares expand_only = True is read; terp migrate make always writes expand_only = False, and adds a comment where every operation it generated is on the list, so the author raises the mark. In upgrade(): create_table (a ForeignKey or ForeignKeyConstraint from it with ondelete CASCADE or SET NULL, onto no table whose model composes SoftDeleteMixin), add_column whose inline Column is nullable, carries a server_default or is Computed, and declares no unique, no CheckConstraint and no ForeignKey but a SET NULL one on a nullable column, create_foreign_key over columns the same revision added nullable with ondelete SET NULL, create_index that is not unique, add_column, create_index, create_unique_constraint, create_check_constraint, create_primary_key and bulk_insert on a table the same revision creates, and a batch_alter_table block (never recreate='always') of such operations, are on the list. Every other Alembic operation, execute(), get_bind(), a merge revision (a tuple down_revision) and a mark that is not a literal bool are flagged, one finding per line. No marker suppresses a finding, and a no_destructive_migrations marker excuses nothing here.

## If you really need an exception

There is none, and no marker suppresses a finding: the way out is the
other answer the rule itself allows, which the intent above states.

## What the check is not required to catch

A check precise enough to have no false positives has limits. This
rule's limits are recorded as data (its corpus's `RESIDUALS.json`), so
where detection ends is a statement rather than a guess:

- an operation made in a helper function that `upgrade()` calls, or through an alias of the operations handle under a method name no operation has, is not required to be seen: the reference stack's migration run refuses it as it executes, which is the half of the rule that sees every operation
- the order of operations inside one revision is not required to be followed: an operation on a table, or over a column, that the same revision creates or adds is admitted wherever it sits in `upgrade()`, while the run admits it only after the creation

**These are not exemptions.** The rule governs those forms exactly as it
governs any other — a checker is simply not required to find them, so
review is the control there. The list only shrinks: closing one means
adding the corpus case that contracts it.

## Enforcement

- Checked while the app runs? Yes — the framework also enforces this while the app runs (fail closed).
- `build-time`: `terp.arch` — `check_expand_revisions_only_expand`
- `runtime`: `terp.migrations` — `assert_operation_on_expand_list`
