# `frontend/no-inline-styling`

**App classes come from local CSS Modules**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/frontend/eslint-boundaries/catalog/frontend/no-inline-styling.json`.

## Why this rule exists

Paint follows the palette, and a framework control keeps the styling and focus treatment it ships with, so a control looks and behaves the same in every app. Inline style and a hardcoded colour in app script paint around the palette, and a class on a framework control, or ink and type an element passes down to the framework component it holds, restyle what the framework owns. So a CSS Module's binding is read only in a className on a native element, naming a class the module defines or choosing between two of them, and a class that sets inherited ink or type goes only on an element that holds the app's own text; a framework control is configured through its props. Inline style, any other class name or read of the binding, and colour literals in app script are refused.

## How Terp realises this

Layout via Stack, Grid, DetailList and the page archetypes from @terpjs/react-core. A layout a component owns: import styles from "./Board.module.css" and className={styles.board}, or className={active ? styles.active : styles.board}, on a native element in the body of a plain Page, with ink and type on the element that holds the app's own text. Paint via the design tokens.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
// terp-allow-no-inline-styling: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## What the check is not required to catch

A check precise enough to have no false positives has limits. This
rule's limits are recorded as data (its corpus's `RESIDUALS.json`), so
where detection ends is a statement rather than a guess:

- a component an element renders through a value or a call written outside it (`const body = <Card />` rendered as `{body}`, a render function's result) is read as the app's own text when the class's inherited ink and type are checked
- an element with a module class inside a framework control's own children (a `Button` label) is not resolved to the surface that control paints, so its ink is held to the admitted surfaces only
- a list marker (`list-style`) is not checked as inherited, so on an element it also reaches a list a framework component renders inside it (a `Markdown` list)

**These are not exemptions.** The rule governs those forms exactly as it
governs any other — a checker is simply not required to find them, so
review is the control there. The list only shrinks: closing one means
adding the corpus case that contracts it.

## Enforcement

- Checked while the app runs? Not yet — a runtime control is planned; the gap is explicit and tracked.
- `build-time`: `@terpjs/eslint-boundaries` — `terp/no-inline-styling`
- `build-time`: `@terpjs/eslint-boundaries` — `BOUNDARY_SPEC.restrictedAttributes`
