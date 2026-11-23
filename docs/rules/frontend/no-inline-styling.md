# `frontend/no-inline-styling`

**App classes come from local CSS Modules**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/frontend/eslint-boundaries/catalog/frontend/no-inline-styling.json`.

## Why this rule exists

Paint follows the theme, and a framework control keeps the styling and focus treatment it ships with, so every palette holds its contrast and a control looks and behaves the same in every app. Inline style and a hardcoded colour in app script paint around the palette, and a class on a framework control restyles what the framework owns. So a class reaches only a native element, through a direct property naming a class its sibling CSS Module defines; a framework control is configured through its props. Inline style, any other class name and colour literals in app script are refused.

## How Terp realises this

Layout via Stack, Grid, DetailList and the page archetypes from @terpjs/react-core. A layout a component owns: import styles from "./Board.module.css" and className={styles.board} on a native element, in the body of a plain Page. Paint via the design tokens, var(--color-...).

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
// terp-allow-no-inline-styling: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? Not yet — a runtime control is planned; the gap is explicit and tracked.
- `build-time`: `@terpjs/eslint-boundaries` — `terp/no-inline-styling`
- `build-time`: `@terpjs/eslint-boundaries` — `BOUNDARY_SPEC.restrictedAttributes`
