# `backend/operations_reference_catalog`

**A route's declared operation is a typed catalog constant, never a bare value**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/operations_reference_catalog.json`.

## Why this rule exists

A route can say what it does for the person calling it, but only by citing a typed definition from one shared catalog -- never a string literal or a value built inline at the call site. Without this, a route's stated purpose could drift from what the catalog documents, or two routes could describe the same action in two different words with no way to tell they were ever meant to agree.

## How Terp realises this

OperationDefinition constants from the control-plane operations catalog, cited via the operation(...) route-level marker and the *_operation= keywords a canonical CRUD factory accepts.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-operations-reference-catalog: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? Yes — the framework also enforces this while the app runs (fail closed).
- `build-time`: `terp.arch` — `check_operations_reference_catalog`
- `runtime`: `terp.core` — `validate_declared_operations`
