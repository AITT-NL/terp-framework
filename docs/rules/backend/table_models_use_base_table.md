# `backend/table_models_use_base_table`

**Every ORM table model inherits the platform base table (no bare tables)**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/table_models_use_base_table.json`.

## Why this rule exists

A table model that skips the platform base table bypasses the framework's managed identity, timestamps, and optimistic-concurrency version — a model living outside the control-plane contract, which every chokepoint (the service layer, audit, concurrency) presupposes.

## How Terp realises this

BaseTable supplies the UUID id, created_at/updated_at and the OCC version; a bare SQLModel table=True model is refused.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-table-models-use-base-table: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? No — this is a property of the written source only; the build-time check is the control, by recorded decision.
- `build-time`: `terp.arch` — `check_table_models_use_base_table`
