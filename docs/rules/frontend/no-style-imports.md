# `frontend/no-style-imports`

**Component styles come from a local CSS Module**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/frontend/eslint-boundaries/catalog/frontend/no-style-imports.json`.

## Why this rule exists

Paint follows the palette and a stylesheet reaches only what its component owns. A global stylesheet, a library's included, paints outside the palettes and reaches every element on the page, so only the bootstrap imports global ones, and only the token pipeline's three. A component may statically default-import its sibling Name.module.css, whose rules select its own classes, named as script identifiers, group them in @media, @container or @supports, and set layout and typography properties and paint. Paint takes a palette role: an ink for color, a surface for a background (one of the three the framework sets its own components on), a border token for a border, chosen so that every admitted ink over every admitted surface is a text pair the palette declares and holds to AA in every theme. A list marker takes a keyword, never copy. Only the exact sibling spelling ./Name.module.css (letters, digits, _, . and - in the name, no query, this letter case) is read, and for it the import opt-out covers the import's form only: a finding inside the module names its CSS line and survives a marker on the import. Any other spelling (another directory, a query, another letter case) is refused as a path, and a marker that waives that refusal leaves the file unread. Global selectors, imports, cross-file composition and a stylesheet loaded through import() or import.meta.glob are refused. The bootstrap's own two sheets, ./house-style.css and ./theme.css, are read as token sheets: custom properties under :root, under a palette's [data-theme] selector, and under :root:not([data-theme]) inside a prefers-color-scheme group, none of them fetching a file, plus @font-face with a source on the app's own origin and @media and @supports groups of these, read with their escapes resolved. Anything else in them is refused with its line and the remedy for its cause, which for the house style's sheet is to fix the style in the tool that writes it, and a marker on their import waives nothing inside them. A rule no token can express goes in a stylesheet of the app's own, imported in the bootstrap under the opt-out, which leaves that file unread.

## How Terp realises this

A component's own layout: import styles from "./Board.module.css", one static default binding, beside the component, with className={styles.board} on a native element. Ink: var(--color-fg-default), var(--color-fg-muted), var(--color-fg-subtle). Surfaces: var(--color-bg-canvas), var(--color-bg-surface), var(--color-bg-subtle). Borders: var(--color-border-default), var(--color-border-strong), var(--color-border-subtle). Otherwise Stack, Grid and the page archetypes from @terpjs/react-core. The bootstrap imports @terpjs/contract/tokens.css, ./house-style.css and ./theme.css. Those two declare tokens only: :root { --radius-control: var(--radius-full); } and [data-theme='night'] { --color-brand-primary: #60a5fa; }, with an app's own typeface in an @font-face whose src is url("/fonts/<file>").

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
// terp-allow-no-style-imports: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## What the check is not required to catch

A check precise enough to have no false positives has limits. This
rule's limits are recorded as data (its corpus's `RESIDUALS.json`), so
where detection ends is a statement rather than a guess:

- a token name in the bootstrap's two sheets is not checked against the token manifest: the sheet's form is held, not its vocabulary, so a misspelt token is admitted and sets nothing
- a stylesheet linked from frontend/index.html (a <link rel="stylesheet"> to a file in public/) is not read: the rule reads the module graph from src/, and the document is not part of it; the policy's style-src 'self' admits such a file, so it is the one global sheet no marker counts

**These are not exemptions.** The rule governs those forms exactly as it
governs any other — a checker is simply not required to find them, so
review is the control there. The list only shrinks: closing one means
adding the corpus case that contracts it.

## Enforcement

- Checked while the app runs? No — this is a property of the written source only; the build-time check is the control, by recorded decision.
- `build-time`: `@terpjs/eslint-boundaries` — `terp/no-style-imports`
- `build-time`: `@terpjs/eslint-boundaries` — `BOUNDARY_SPEC.styleImportPatterns`
