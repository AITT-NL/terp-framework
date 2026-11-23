# `frontend/no-style-imports`

**Component styles come from a local CSS Module**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/frontend/eslint-boundaries/catalog/frontend/no-style-imports.json`.

## Why this rule exists

Paint follows the palette and a stylesheet reaches only what its component owns. A global stylesheet, a library's included, paints outside the palettes and reaches every element on the page, so only the bootstrap imports global ones, and only the token pipeline's three. A component may statically default-import its sibling Name.module.css, whose rules select its own classes, named as script identifiers, group them in @media, @container or @supports, and set layout and typography properties and paint. Paint takes a palette role: an ink for color, a surface for a background (one of the three the framework sets its own components on), a border token for a border, chosen so that every admitted ink over every admitted surface is a text pair the palette declares and holds to AA in every theme. A list marker takes a keyword, never copy. Only the exact sibling spelling ./Name.module.css (letters, digits, _, . and - in the name, no query, this letter case) is read, and for it the import opt-out covers the import's form only: a finding inside the module names its CSS line and survives a marker on the import. Any other spelling (another directory, a query, another letter case) is refused as a path, and a marker that waives that refusal leaves the file unread. Global selectors, imports, cross-file composition and a stylesheet loaded through import() or import.meta.glob are refused.

## How Terp realises this

A component's own layout: import styles from "./Board.module.css", one static default binding, beside the component, with className={styles.board} on a native element. Ink: var(--color-fg-default), var(--color-fg-muted), var(--color-fg-subtle). Surfaces: var(--color-bg-canvas), var(--color-bg-surface), var(--color-bg-subtle). Borders: var(--color-border-default), var(--color-border-strong), var(--color-border-subtle). Otherwise Stack, Grid and the page archetypes from @terpjs/react-core. The bootstrap imports @terpjs/contract/tokens.css, ./house-style.css and ./theme.css.

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
