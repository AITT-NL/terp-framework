# `backend/path_id_params_are_uuid`

**A route path parameter naming a resource id must be typed as a UUID**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/path_id_params_are_uuid.json`.

## Why this rule exists

A URL path segment that names a resource id (spelled id or ending in _id) identifies a specific row, and the platform issues UUID identifiers. Typing that path parameter as a UUID rejects a malformed identifier at the request boundary, before it reaches the data layer, instead of letting an untyped or wrongly-typed value through. Only path parameters are in scope; query and body parameters are unaffected.

## How Terp realises this

A handler parameter that also appears in the route decorator's URL template and is named id or ends in _id must be annotated uuid.UUID (a uuid.UUID attribute or a bare UUID name); a missing or non-UUID annotation is flagged at the handler.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-path-id-params-are-uuid: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? No — this is a property of the written source only; the build-time check is the control, by recorded decision.
- `build-time`: `terp.arch` — `check_path_id_params_are_uuid`
