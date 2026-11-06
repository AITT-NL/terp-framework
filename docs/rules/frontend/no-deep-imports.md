# `frontend/no-deep-imports`

**App modules import platform packages from the root only**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/frontend/eslint-boundaries/catalog/frontend/no-deep-imports.json`.

## Why this rule exists

A deep import into a platform package's internals couples the app to files that are free to move; the package root is the published, stable surface. The refused path segments are declared in restricted-surface.json (deepImportPathSegments).

## How Terp realises this

@terpjs/*/src/* and @terpjs/*/dist/* imports are refused; import from the @terpjs/* package root.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
// terp-allow-no-deep-imports: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? No — this is a property of the written source only; the build-time check is the control, by recorded decision.
- `build-time`: `@terpjs/eslint-boundaries` — `BOUNDARY_SPEC.internalImportPatterns`
