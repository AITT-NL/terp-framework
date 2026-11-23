# `frontend/no-style-imports`

**Component styles come from a local CSS Module**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/frontend/eslint-boundaries/catalog/frontend/no-style-imports.json`.

## Why this rule exists

Paint follows the theme and a stylesheet reaches only what its component owns. A global stylesheet, a library's included, paints outside the palettes and reaches every element on the page, so only the bootstrap imports global ones, and only the token pipeline's three. A component may statically default-import its sibling Name.module.css, whose rules select its own classes, group them in @media, @container or @supports, set layout and typography properties and take paint only from theme tokens; framework controls keep their own focus treatment. The import opt-out covers the import's form only: a finding inside the module names its CSS line and survives a marker on the import. Global selectors, imports, cross-file composition and a stylesheet loaded through import() or import.meta.glob are refused.

## How Terp realises this

A component's own layout: import styles from "./Board.module.css", one static default binding, beside the component, with className={styles.board} on a native element. Otherwise Stack, Grid and the page archetypes from @terpjs/react-core. The bootstrap imports @terpjs/contract/tokens.css, ./house-style.css and ./theme.css.

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
