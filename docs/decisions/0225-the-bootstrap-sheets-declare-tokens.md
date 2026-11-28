# 0225 — The bootstrap's own sheets declare tokens, and nothing else

- **Status:** Proposed on 2026-11-28. Held by `packages/frontend/eslint-boundaries/src/index.test.js`
  ("reads the bootstrap's own sheets as token sheets (ADR 0225)", which pins each refusal's line,
  cause and remedy, the shapes a styling tool writes, and that a marker on the import waives
  nothing inside), `findings.test.js` ("rechecks the bootstrap when only one of its token sheets
  changes"), the `no-style-imports` corpus cases `violation-05` and `compliant-03`, and the rule's
  recorded residual. Amends [ADR 0094](0094-attribute-keyed-styling.md),
  [ADR 0097](0097-shell-parameters-and-ordered-navigation.md),
  [ADR 0175](0175-the-frontend-boundary-does-not-stop-at-the-module-tree.md),
  [ADR 0217](0217-app-components-can-own-a-scoped-stylesheet.md) and
  [ADR 0223](0223-type-and-shape-have-roles-as-colour-does.md); their status lines say how.
- **Date:** 2026-11-28.
- **Relates:** [ADR 0103](0103-the-ideology-one-pattern-enforced-escapable-by-proof.md) (escape is
  possible and never quiet), [ADR 0122](0122-the-catalog-is-frozen-at-its-breadth-and-grows-in-legibility.md) (a correction to
  an existing rule rather than a new one), [ADR 0104](0104-the-spa-document-carries-its-own-security-headers.md)
  (`font-src 'self'`), and in terp-studio ADR 0031 (the house style's own sheet).

## Context

The bootstrap imports three global stylesheets and no others: the framework's tokens,
`house-style.css`, which an organisation's styling tool writes, and `theme.css`, the app's own.
`frontend/no-style-imports` refuses every other stylesheet and reads every CSS Module, and read
neither of the two. Anything could go in them, and ADR 0094 made sure it would win: every rule in
react-core's layered sheet loses to an unlayered one, so a selector on a react-core marker in
`theme.css` restyles a component. That was meant as the way an app restyles the framework. It has
three faults, each of which ADR 0223 named:

- **Nothing checks it.** The CSS Module vocabulary holds paint to the palette's roles so every ink
  over every surface is a pair the palette measures; a rule in `theme.css` paints with anything.
- **It is not a contract.** A `data-terp` marker is how react-core selects its own elements, not a
  published surface (ADR 0160): a rule keyed on one breaks without a word the day the marker moves.
- **It is the quiet route.** ADR 0103 requires an escape to be explicit, greppable, justified and
  counted. A rule in `theme.css` is none of those, and an agent asked to "make the cards square"
  had no reason to prefer the token to it.

The tokens can now say what that route was mostly used for. ADR 0223 gave type and shape roles;
the palettes, the shell's geometry, density and the brand mark were tokens or declarations
already. So the two sheets can be held to what they are for.

## Decision

### 1. `no-style-imports` reads the two bootstrap sheets, as token sheets

When the bootstrap (`src/main.tsx` or `src/main.ts`) imports `./house-style.css` or `./theme.css`,
the rule reads the file and admits:

- **Tokens under the selectors a palette uses**: `:root`, `[data-theme='<palette>']` (any quoting,
  alone or in a list with its earlier names), and `:root:not([data-theme])` inside an
  `@media (prefers-color-scheme: …)` group, which is how a palette follows the viewer's platform.
  Studio's house-style writer emits exactly these shapes, and the template's sheets are comments.
- **Custom properties only** in those rules, without `!important` and without `url()`: no token
  holds a file.
- **`@font-face`**, with its descriptors only and a `src` on the app's own origin, so the policy's
  `font-src 'self'` admits it: an app's own typeface is a file it serves (ADR 0223 §4).
- **`@media` groups** of the above, and comments.

Everything else is refused, each with its line and the remedy: another selector, a standard
property, any other at-rule (`@import`, `@layer`, `@keyframes`), a nested rule. A sheet that is
not there is the bundler's to refuse, and is not a finding.

### 2. A correction to an existing rule, not a new one

ADR 0122 froze the catalog's breadth. This does not add to it: `no-style-imports`' intent already
says a global stylesheet paints outside the palettes and reaches every element on the page, and
the two sheets the bootstrap may import were the one place it did not look. The finding is the
rule's existing `stylesheetContent`, reported on the import with the sheet's line in the message,
exactly as a CSS Module's is.

### 3. The escape is the one there already was

A rule a token cannot express goes in a stylesheet of the app's own, imported in `src/main.tsx`
under a justified `// terp-allow-no-style-imports: <reason>` marker. That waives the path refusal,
leaves the file unread, and is counted against the escape-hatch budget and decided by a human
(ADR 0059). A marker on the `./theme.css` import waives nothing inside it, as a marker on a CSS
Module's import waives nothing inside the module (ADR 0217): the import's form is always allowed,
and the sheet's content is not the import's to waive. So nothing is forbidden outright, and
nothing that was quiet stays quiet.

## What it amends

- **ADR 0094**: an app's `theme.css` is still unlayered and still wins the cascade, for the
  tokens it declares. Restyling a react-core rule from it is refused; the route for a rule no token
  can express is a stylesheet under the marker.
- **ADR 0097**: turning the scrollbar gutter off is a rule on `html`, so it moves from `theme.css`
  to that stylesheet.
- **ADR 0175**: the bootstrap still imports exactly the token pipeline's three sheets; the two
  that are the app's and the house's are now read.
- **ADR 0217**: the escape it describes is the one this names; nothing about CSS Modules changes.
- **ADR 0223**: a step declared again below the root is no longer possible from `theme.css`, so
  the caveat about roles resolving on the root has nowhere left to bite except a stylesheet under
  the marker.

## Runtime

`not-applicable`, as the rule already records: once the bundler has compiled the sheets into the
emitted CSS, which rule came from which file no longer exists. The font origin has its own
runtime control in the policy, `font-src 'self'`, which refuses a face from another origin in the
browser whether or not this lint ran.

## What it does not do

- **It does not check token names.** A misspelt token is admitted: the sheet's form is checked,
  not its vocabulary. That is recorded as a residual of the rule, and the token manifest is where
  a tool or an agent finds the names.
- **It does not touch CSS Modules** or what they may paint.
- **It does not read the third sheet.** `@terpjs/contract/tokens.css` is the framework's own and
  is read by the framework's tests.
- **It does not touch the template's sheets.** Both ship as comments, and the template test that
  lints the generated bootstrap clean holds them to this.
