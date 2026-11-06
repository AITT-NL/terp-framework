# `frontend/router-links`

**In-app links go through the router, never a raw anchor**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/frontend/eslint-boundaries/catalog/frontend/router-links.json`.

## Why this rule exists

A raw <a href="/..."> forces a full reload and skips the role-aware route guard; in-app navigation uses the stack's router-integrated link. External https:// anchors stay allowed.

## How Terp realises this

Link from @terpjs/react-core (router-integrated, role-aware).

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
// terp-allow-router-links: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? No — this is a property of the written source only; the build-time check is the control, by recorded decision.
- `build-time`: `@terpjs/eslint-boundaries` — `BOUNDARY_SPEC.restrictInAppAnchors`
