# `backend/no_unique_columns_on_soft_delete_models`

**Soft-delete models never declare a full-table unique constraint (dead rows block reuse)**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/no_unique_columns_on_soft_delete_models.json`.

## Why this rule exists

A soft-deleted row stays in the table, so it keeps occupying every full-table unique index: the "deleted" value (an email, a slug, a code) can never be used again, surfacing as an inexplicable conflict long after the delete. Scope uniqueness to the live rows with a partial unique index that excludes soft-deleted rows — which this rule accepts — or deactivate instead of deleting.

## How Terp realises this

A partial unique index in __table_args__ (unique=True with postgresql_where / sqlite_where on deleted_at IS NULL) is the accepted shape; the identity user table keeps email unique by deactivating instead of deleting.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-no-unique-columns-on-soft-delete-models: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? No — this is a property of the written source only; the build-time check is the control, by recorded decision.
- `build-time`: `terp.arch` — `check_no_unique_columns_on_soft_delete_models`
