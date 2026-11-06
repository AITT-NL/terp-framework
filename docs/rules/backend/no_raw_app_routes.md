# `backend/no_raw_app_routes`

**App code never registers HTTP surface on the composed app object**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/no_raw_app_routes.json`.

## Why this rule exists

Composition mounts every module router behind the deny-by-default policy guard. Surface registered on the composed app itself — a mount, an included router, a directly added route, a verb decorator on the composed app, or a lifecycle hook — is served or executed WITHOUT that guard and is invisible to the module permission model. Modules declare one flat router in their manifest; composition mounts it.

## How Terp realises this

app.mount / app.include_router / app.add_route / verb decorators / app.on_event / app.add_event_handler on the create_app-produced app are refused; modules declare one router on their ModuleSpec.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-no-raw-app-routes: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? Yes — the framework also enforces this while the app runs (fail closed).
- `build-time`: `terp.arch` — `check_no_raw_app_routes`
- `runtime`: `terp.core` — `freeze_app_route_registration`
