# `backend/no_manual_scope_filtering`

**Modules never touch the framework-managed scope columns**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/no_manual_scope_filtering.json`.

## Why this rule exists

Soft-delete and tenant scoping are applied centrally: the composed base read query filters out soft-deleted rows and applies every registered row predicate (e.g. the tenant filter), and the audited delete chokepoint stamps the deletion. A module that references deleted_at / tenant_id — to filter, set, or compare — is re-implementing that scope predicate by hand, which can leak or destroy scoped rows. The composed scoped read is the only path; expose the column in a read DTO if you must surface it, but never filter or assign it in module code. Unlike the actor-stamp rule, a plain read of these columns is refused too, and deliberately: `if row.deleted_at is None` inside module code IS the hand-rolled scope predicate this rule exists to replace, and no static check can tell it from a read that only surfaces the value.

## How Terp realises this

BaseService.base_query composes the scope (deleted_at IS NULL + registered predicates); deleted_at / tenant_id attribute access in module code is refused.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-no-manual-scope-filtering: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? Yes — the framework also enforces this while the app runs (fail closed).
- `build-time`: `terp.arch` — `check_no_manual_scope_filtering`
- `runtime`: `terp.core` — `apply_row_scope`
