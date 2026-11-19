# `frontend/no-inline-styling`

**App classes come from local CSS Modules**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/frontend/eslint-boundaries/catalog/frontend/no-inline-styling.json`.

## Why this rule exists

Apply classes to native elements through a direct property naming a class defined in a sibling CSS Module. Configure framework controls through their component props. Inline style, arbitrary class names and hardcoded color literals in app script are refused.

## How Terp realises this

Use theme tokens for component colors, typography and spacing. Use a plain Page for a custom screen.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
// terp-allow-no-inline-styling: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? No — this is a property of the written source only; the build-time check is the control, by recorded decision.
- `build-time`: `@terpjs/eslint-boundaries` — `terp/no-inline-styling`
- `build-time`: `@terpjs/eslint-boundaries` — `BOUNDARY_SPEC.restrictedAttributes`
