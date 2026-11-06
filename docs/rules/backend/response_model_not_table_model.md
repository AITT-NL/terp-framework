# `backend/response_model_not_table_model`

**A route's declared response type is a read DTO, never the persisted table model**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/response_model_not_table_model.json`.

## Why this rule exists

routes_declare_response_model proves a response type is declared; this rule proves it is not the persisted table itself. A declared response type set to a table model — directly or wrapped in a page envelope or collection — serializes the stored row, so a column such as a password hash leaks straight through the boundary. Return a read DTO listing exactly the safe fields instead.

## How Terp realises this

response_model set to a table=True model, directly or wrapped in Page[...] / list[...] (the Page[User] footgun), is refused; return a *Read schema on terp.core.BaseSchema.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-response-model-not-table-model: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? Yes — the framework also enforces this while the app runs (fail closed).
- `build-time`: `terp.arch` — `check_response_model_not_table_model`
- `runtime`: `terp.core` — `validate_router_response_models`
