# `backend/no_cross_module_imports`

**A module imports a sibling only across an edge it declared**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/no_cross_module_imports.json`.

## Why this rule exists

Modules are independent by default; a real dependency is DECLARED, never implicit. The depending module names the sibling as a dependency edge in its own manifest, which puts the coupling where a reader already looks; an undeclared sibling import is refused. Both absolute and relative sibling imports are caught: a relative import is resolved to its absolute module first, so renaming the import style does not re-couple two leaf modules. The declaration is read from source, so one a static reader cannot resolve grants nothing (fail closed).

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-no-cross-module-imports: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? No — this is a property of the written source only; the build-time check is the control, by recorded decision.
- `build-time`: `terp.arch` — `check_no_cross_module_imports`
