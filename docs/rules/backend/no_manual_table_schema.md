# `backend/no_manual_table_schema`

**Table models never hand-write a physical schema placement (the layout is managed)**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/no_manual_table_schema.json`.

## Why this rule exists

The physical schema layout is a deployment decision: under the flat layout every table lives in the default schema, and under the per-module layout the migration runtime routes each package's tables into its own database schema — in both layouts the model metadata stays schema-free. A hand-written schema placement pins one table to a fixed schema, silently escaping the managed layout (and breaking lightweight dev/test databases that parse a schema prefix differently).

## How Terp realises this

DB_SCHEMA_LAYOUT (flat / per-module via search_path, ADR 0070) owns placement; __table_args__ = {"schema": ...} is refused.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-no-manual-table-schema: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? No — this is a property of the written source only; the build-time check is the control, by recorded decision.
- `build-time`: `terp.arch` — `check_no_manual_table_schema`
