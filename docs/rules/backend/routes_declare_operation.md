# `backend/routes_declare_operation`

**Every route declares the operation it performs**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/routes_declare_operation.json`.

## Why this rule exists

A route's method and path say how to call it; nothing about them says what it does for the person calling it. Under this app's chosen coverage level, a route that declares no operation leaves that question permanently unanswered for anyone reading the permission surface rather than the source.

## How Terp realises this

the operation(...) route-level marker, or for a canonical CRUD factory its *_operation= keywords, checked once the app's operations catalog opts into strict coverage.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-routes-declare-operation: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? Yes — the framework also enforces this while the app runs (fail closed).
- `build-time`: `terp.arch` — `check_routes_declare_operation`
- `runtime`: `terp.core` — `validate_declared_operations`
