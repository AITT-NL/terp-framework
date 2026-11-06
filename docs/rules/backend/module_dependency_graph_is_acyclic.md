# `backend/module_dependency_graph_is_acyclic`

**Declared module dependency edges form a DAG**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/module_dependency_graph_is_acyclic.json`.

## Why this rule exists

A cycle is the point at which two 'independent' modules have quietly become one: neither can be read, tested, deployed or removed without the other, and the direction that would say which owns the shared concept no longer exists. Refusing the cycle rather than the coupling keeps the available fixes the real ones — extract the shared concept into a module both depend on, or invert the weaker direction into an event subscription.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-module-dependency-graph-is-acyclic: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? Yes — the framework also enforces this while the app runs (fail closed).
- `build-time`: `terp.arch` — `check_module_dependency_graph_is_acyclic`
- `runtime`: `terp.core` — `validate_requires`
