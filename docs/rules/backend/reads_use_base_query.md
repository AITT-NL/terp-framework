# `backend/reads_use_base_query`

**A scope-trait model is read through the composed scoped query, never a raw query built from scratch**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/reads_use_base_query.json`.

## Why this rule exists

A model that mixes a soft-delete or tenant-scope trait carries row scope. A bespoke read that queries the model directly — instead of building on the composed scoped query — drops that scope, leaking soft-deleted or cross-tenant rows (closing the composition point to overrides did not close a new read method that never calls it). Build reads on the scoped query and the declared filter seam; the request session applies the scope to every ORM read as the runtime backstop (the mapped entities a statement reaches through its columns, joins, predicates and nested selects, aggregates included), and this rule is the build-time early warning. A read that names a scoped table only through its Core table reaches no mapped entity for the session to scope, so this rule is the only control for it, and only where the source names the model. The one sanctioned raw query — the scoped composition point itself — lives in the framework, not a module, so it is never scanned here.

## How Terp realises this

select(Model) on a SoftDeleteMixin / TenantScopedMixin model is refused in modules (ADR 0017, F1); build on base_query() / business_filters(), with apply_row_scope as the runtime backstop.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-reads-use-base-query: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? Yes — the framework also enforces this while the app runs (fail closed).
- `build-time`: `terp.arch` — `check_reads_use_base_query`
- `runtime`: `terp.core` — `apply_row_scope`
