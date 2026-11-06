# `frontend/no-unsafe-target-blank`

**A static target="_blank" link declares rel="noopener"**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/frontend/eslint-boundaries/catalog/frontend/no-unsafe-target-blank.json`.

## Why this rule exists

Without rel=noopener the opened page holds a window.opener reference to the app — the reverse-tabnabbing primitive. The rule enforces the safe default on every statically-authored external link.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
// terp-allow-no-unsafe-target-blank: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? No — this is a property of the written source only; the build-time check is the control, by recorded decision.
- `build-time`: `@terpjs/eslint-boundaries` — `terp/no-unsafe-target-blank`
