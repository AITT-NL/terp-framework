# `backend/no_app_instantiation`

**App code never constructs the web application object directly**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/no_app_instantiation.json`.

## Why this rule exists

The framework's composer owns app composition (deny-by-default guards, the control plane, the error envelope). A hand-built application object is an application assembled outside the framework — it acquires none of those controls.

## How Terp realises this

terp.core.create_app composes the app; a bare FastAPI() constructor call is refused.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-no-app-instantiation: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? No — this is a property of the written source only; the build-time check is the control, by recorded decision.
- `build-time`: `terp.arch` — `check_no_app_instantiation`
