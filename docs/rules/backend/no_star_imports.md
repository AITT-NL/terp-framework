# `backend/no_star_imports`

**Import names explicitly, never with a wildcard**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/no_star_imports.json`.

## Why this rule exists

A wildcard import pulls an unknown, changeable set of names into a namespace, so the module's real dependency surface is invisible and one upstream rename can silently shadow a local name. Naming each import keeps the dependency graph legible to readers and to the boundary checks that police it.

## How Terp realises this

A 'from <module> import *' statement is refused; list the specific names the module uses instead.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-no-star-imports: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? No — this is a property of the written source only; the build-time check is the control, by recorded decision.
- `build-time`: `terp.arch` — `check_no_star_imports`
