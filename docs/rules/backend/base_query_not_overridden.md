# `backend/base_query_not_overridden`

**A service never overrides the scoped base read query — read filters compose through the declared filter seam**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/base_query_not_overridden.json`.

## Why this rule exists

The base read query composes the non-droppable row scope (soft-delete plus every registered capability predicate, e.g. tenancy) with the service's declared business filters. Overriding that composition point — the old, footgun-y seam — can silently drop soft-delete or tenant scoping the moment the override forgets to delegate up the chain, leaking soft-deleted or cross-tenant rows. Add static read conditions through the declared filter seam (it returns conditions, not a query, so scope cannot be dropped); a per-call filter belongs in a bespoke read built on the scoped base query.

## How Terp realises this

BaseService.base_query composes the scope; add filters via business_filters(), or build bespoke reads on base_query().where(...) (ADR 0017).

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-base-query-not-overridden: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? Yes — the framework also enforces this while the app runs (fail closed).
- `build-time`: `terp.arch` — `check_base_query_not_overridden`
- `runtime`: `terp.core` — `apply_row_scope`
