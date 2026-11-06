# `frontend/no-cross-module-imports`

**An app module never imports a sibling module**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/frontend/eslint-boundaries/catalog/frontend/no-cross-module-imports.json`.

## Why this rule exists

Modules couple only through the platform packages and their own files. A sibling import — static, dynamic import(), relative or via the app alias — creates hidden coupling that breaks module isolation and independent evolution.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
// terp-allow-no-cross-module-imports: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? No — this is a property of the written source only; the build-time check is the control, by recorded decision.
- `build-time`: `@terpjs/eslint-boundaries` — `terp/no-cross-module-imports`
