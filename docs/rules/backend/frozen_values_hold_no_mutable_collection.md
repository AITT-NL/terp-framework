# `backend/frozen_values_hold_no_mutable_collection`

**A frozen value object must not hold a mutable collection**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/frozen_values_hold_no_mutable_collection.json`.

## Why this rule exists

Freezing a value object announces that it cannot change after construction, and callers rely on that: they share it between requests, cache it, use it as a registry key, and skip defensive copies because the type says none are needed. Freezing binds the ATTRIBUTES, not what they point at — a frozen object holding a list or a dict or a set is immutable only one level deep, so anyone holding it can append to its contents while every guarantee the type advertises still appears to hold. The mutation is invisible at the call site that performs it and arrives somewhere else entirely, in another request or another worker, as state that changed without an assignment. A frozen field must therefore be typed as an immutable sequence or mapping, so the promise the type makes is the promise it keeps.

## How Terp realises this

Flagged on the field of a frozen value object whose annotation is a mutable built-in collection — list, dict or set, including their typing spellings and parameterised forms — with the immutable counterpart named in the message: a tuple for a sequence, a Mapping or frozen mapping for a dict, a frozenset for a set. A frozen object is recognised by its declaration, not by convention: a dataclass frozen at the decorator, a NamedTuple, or a model configured immutable. An annotation that is not statically a mutable collection is not judged, because the shape of an aliased or computed type is not knowable here and guessing would reject correct code.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-frozen-values-hold-no-mutable-collection: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? No — this is a property of the written source only; the build-time check is the control, by recorded decision.
- `build-time`: `terp.arch` — `check_frozen_values_hold_no_mutable_collection`
