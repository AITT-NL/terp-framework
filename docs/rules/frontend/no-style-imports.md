# `frontend/no-style-imports`

**Module-authored stylesheets are refused**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/frontend/eslint-boundaries/catalog/frontend/no-style-imports.json`.

## Why this rule exists

Importing a stylesheet from an app module reintroduces per-screen CSS; theming flows from the app's token source only. The refused stylesheet extensions are declared in restricted-surface.json (styleImportExtensions).

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
// terp-allow-no-style-imports: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? No — this is a property of the written source only; the build-time check is the control, by recorded decision.
- `build-time`: `@terpjs/eslint-boundaries` — `BOUNDARY_SPEC.styleImportPatterns`
