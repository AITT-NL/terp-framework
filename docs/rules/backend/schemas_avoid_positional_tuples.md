# `backend/schemas_avoid_positional_tuples`

**A schema field never crosses the wire as a positional tuple**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/schemas_avoid_positional_tuples.json`.

## Why this rule exists

A fixed-length tuple annotation (tuple[str, str], list[tuple[str, int]]) on a schema a client can see or send serialises into the contract as an array whose element types are positional (prefixItems, or the list form of items). Client generators do not agree on that shape: one emits the positional form and another the widened element array, so the two descriptions of the same field are structurally unrelated and the app cannot type its own calls against its own API — the failure surfaces at the call site as an opaque generic-instantiation mismatch, far from the field that caused it, and only with error truncation disabled. A fixed tuple is also a poor contract in its own right: the positions carry meaning that no name records. Name the shape instead — a nested model with named fields when the positions differ in meaning, or a homogeneous sequence when they do not. Scope is the positional shape only: a variadic tuple[X, ...] serialises byte-identically to list[X] — it is the immutable spelling of a homogeneous sequence, the natural annotation for a frozen value object — so it is compliant, and refusing it would force a source rewrite with zero wire effect. A fixed tuple nested inside one (tuple[tuple[str, int], ...]) is still refused.

## How Terp realises this

Schema fields annotated with a nested BaseSchema model or a homogeneous sequence (list[...], or the variadic tuple[X, ...] which serialises identically); fixed-length tuple[...] annotations on BaseSchema subclasses and on any class used as a route body or response_model are refused.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-schemas-avoid-positional-tuples: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? Yes — the framework also enforces this while the app runs (fail closed).
- `build-time`: `terp.arch` — `check_schemas_avoid_positional_tuples`
- `runtime`: `terp.core` — `reject_positional_tuple_schemas`
