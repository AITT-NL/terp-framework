# `frontend/no-style-imports`

**Component styles come from a local CSS Module**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/frontend/eslint-boundaries/catalog/frontend/no-style-imports.json`.

## Why this rule exists

App components may statically default-import a sibling Name.module.css file. Its rules style local classes and may group them with media, container or supports conditions. Use supported layout and typography properties and theme tokens for paint. Framework controls own their focus treatment. The import opt-out covers the import form only. Findings inside a sibling module identify the CSS line and survive an import opt-out. Global selectors, imports and cross-file composition are refused. The bootstrap may also import the three token stylesheets.

## How Terp realises this

Use theme tokens for component colors, typography and spacing. Use a plain Page for a custom screen.

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
- `build-time`: `@terpjs/eslint-boundaries` — `terp/no-style-imports`
- `build-time`: `@terpjs/eslint-boundaries` — `BOUNDARY_SPEC.styleImportPatterns`
