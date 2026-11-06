# `backend/cross_module_imports_use_public_surface`

**A declared module edge grants models / schemas / service / events only**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/cross_module_imports_use_public_surface.json`.

## Why this rule exists

A declared dependency buys the other module's domain vocabulary, not its delivery surface. Importing another module's router couples the two through HTTP shapes and lets an in-process call walk past the authorization policy that guards those routes; importing an underscore-prefixed submodule takes a dependency on something its owner never published; importing the bare package depends on whatever that package happens to re-export. The edge is therefore bounded to the published surface, so the dependency stays a contract rather than a keyhole into the other module's implementation.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-cross-module-imports-use-public-surface: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? No — this is a property of the written source only; the build-time check is the control, by recorded decision.
- `build-time`: `terp.arch` — `check_cross_module_imports_use_public_surface`
