# `frontend/no-untranslated-ui`

**Static user-facing text participates in localization**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/frontend/eslint-boundaries/catalog/frontend/no-untranslated-ui.json`.

## Why this rule exists

Static user-facing text anywhere in app-authored frontend source must use the translation seam. Bare visible copy, accessibility labels, component text properties, labels stored in data, and standard toast feedback are otherwise absent from every translation catalog and silently remain in the source language. The subject is text that is rendered. An operand of a comparison is not: the expression evaluates to a boolean, so the literal in `status === "paused"` is a state token being tested and reaches no screen in any locale. The same holds for the left operand of `&&`, which is the test rather than what renders. Operators that can render either side - `||`, `??` and string concatenation - are in scope on both. A property that is not text is not in scope whatever its value spells: `columns="auto"` on a layout component is a keyword, and the same name is text only where the component takes it as text.

## How Terp realises this

Use UiText descriptors and Trans from @terpjs/react-core throughout app-authored frontend source. A status guard needs no hoisting: `{status === "paused" && <Trans .../>}` is compliant as written, and so is a comparison against a literal anywhere else.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
// terp-allow-no-untranslated-ui: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? No — this is a property of the written source only; the build-time check is the control, by recorded decision.
- `build-time`: `@terpjs/eslint-boundaries` — `terp/no-untranslated-ui`
