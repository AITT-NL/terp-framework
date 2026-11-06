# `backend/forwarded_filters_are_declared`

**Every filter name a read endpoint forwards must be a declared filter**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/forwarded_filters_are_declared.json`.

## Why this rule exists

An endpoint that narrows a read forwards its optional query parameters unchanged, so a filter name that matches no declaration carries no value on any request that omits that parameter. The narrowing appears to be applied while the read stays unnarrowed, and no test that omits the parameter can observe the difference. Each forwarded filter name must correspond to a filter the read layer declares, so a name that no declaration backs is rejected on the source rather than on the one request that happens to supply a value for it.

## How Terp realises this

A literal filter name forwarded from an endpoint that matches no declared filter is flagged at that name, and the message lists the declared names so a misspelling is visible against its intended target. Names that are not statically knowable — a filter mapping built elsewhere, or a computed name — are not judged, because a guess there would reject correct code.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-forwarded-filters-are-declared: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? Yes — the framework also enforces this while the app runs (fail closed).
- `build-time`: `terp.arch` — `check_forwarded_filters_are_declared`
- `runtime`: `terp.core` — `resolve_filters`
