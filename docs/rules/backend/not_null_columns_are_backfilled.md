# `backend/not_null_columns_are_backfilled`

**A NOT NULL column added to an existing table must back-fill the rows it meets**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/not_null_columns_are_backfilled.json`.

## Why this rule exists

Autogenerate emits `add_column(sa.Column(..., nullable=False))` for a new non-nullable field, and it is the one line of a generated revision whose correctness the generator cannot judge: the statement succeeds against an empty database and fails against one that holds rows, because every row already there needs a value the statement never supplies. The failure therefore lands as far from its cause as a schema change can — a migration test upgrades a fresh scratch database, where the statement is correct, so the revision passes the suite and passes review before failing on the first environment that has data. A `server_default` settles it: the database fills the existing rows as it adds the column, and new rows still take the model-side default. Where no literal default is right, the expand/contract shape applies instead — add the column nullable, back-fill it, tighten it in a later release.

## How Terp realises this

In upgrade(), an add_column(...) whose inline Column declares nullable=False and no server_default is flagged, on the direct call and inside a batch_alter_table block alike. create_table is out of scope (a table created here holds no rows), and so is a column added to a table the same upgrade() creates. A table name that is not a string literal is read as one that may hold rows. The standard # arch-allow-not-null-columns-are-backfilled marker (budgeted) justifies a reviewed case.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-not-null-columns-are-backfilled: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? No — this is a property of the written source only; the build-time check is the control, by recorded decision.
- `build-time`: `terp.arch` — `check_not_null_columns_are_backfilled`
