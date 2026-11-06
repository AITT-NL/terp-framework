# `frontend/locale-catalogs-complete`

**Every declared target locale translates every authored message**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/frontend/eslint-boundaries/catalog/frontend/locale-catalogs-complete.json`.

## Why this rule exists

Every stable user-interface message identifier must have a non-empty translation in every declared target locale. A missing or malformed catalog, empty entries, and undocumented source-language copies fail the gate instead of silently rendering source-language text after a user switches locale. A descriptor is written where it is used, with its identifier and source message as literals: a function that builds one from its own parameters is refused, because every call through it carries its copy in the call's arguments, where the inventory never looks, so a missing translation would pass. A record built from data (from a member of the record, a destructured object, or a key into data) is not a descriptor factory and is not refused.

## How Terp realises this

Declare sourceLocale and locale message maps in frontend/i18n.json; the boundary rule and defineAppLocales validate that declaration, while LocaleProvider refuses missing target entries at render time. Write { id: "...", message: "..." } or Trans where the text is used; a positional helper such as (id, message) => ({ id, message }) is reported.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
// terp-allow-locale-catalogs-complete: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? Yes — the framework also enforces this while the app runs (fail closed).
- `build-time`: `@terpjs/eslint-boundaries` — `terp/locale-catalogs-complete`
- `runtime`: `@terpjs/react-core` — `LocaleProvider`
