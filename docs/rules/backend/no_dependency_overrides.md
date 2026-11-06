# `backend/no_dependency_overrides`

**App code never rebinds the composed app's dependency injections**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/no_dependency_overrides.json`.

## Why this rule exists

Composition binds the authentication and session seams once. Rebinding the app's dependency-override map in app code (e.g. replacing the principal provider) silently disables authentication or swaps the database session outside every guard. Overrides are a TEST-ONLY seam; application code has no legitimate use.

## How Terp realises this

app.dependency_overrides on the create_app-composed app is the refused surface; composition binds the seams (create_app(principal_provider=...)) before the freeze.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-no-dependency-overrides: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? Yes — the framework also enforces this while the app runs (fail closed).
- `build-time`: `terp.arch` — `check_no_dependency_overrides`
- `runtime`: `terp.core` — `freeze_dependency_overrides`
