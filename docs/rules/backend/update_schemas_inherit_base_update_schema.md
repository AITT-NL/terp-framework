# `backend/update_schemas_inherit_base_update_schema`

**An update request contract must require the optimistic-concurrency token**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/update_schemas_inherit_base_update_schema.json`.

## Why this rule exists

Optimistic concurrency only protects a row when the client echoes the version it loaded and the update path checks it before writing. That guarantee hinges on the update request contract demanding the token as a required field: an update contract that omits it lets a client send a blind write, so the check has nothing to compare and a concurrent edit is silently overwritten (a lost update). Every update request contract must inherit the shared concurrency-bearing base that makes the token a required field, rather than an ordinary contract that leaves it out. The token is not redeclared on the contract — it is a managed field that arrives by inheritance.

## How Terp realises this

class NoteUpdate(BaseSchema) is refused; class NoteUpdate(BaseUpdateSchema) (directly or transitively) is compliant, as is a class wired as build_crud_router(update_schema=...). BaseUpdateSchema supplies the required version field; BaseService.update checks it.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-update-schemas-inherit-base-update-schema: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? Yes — the framework also enforces this while the app runs (fail closed).
- `build-time`: `terp.arch` — `check_update_schemas_inherit_base_update_schema`
- `runtime`: `terp.core` — `BaseUpdateSchema`
- `runtime`: `terp.core` — `StaleDataError`
