# `backend/no_raw_session_construction`

**App code never constructs a database session or engine; it uses the injected request session**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/no_raw_session_construction.json`.

## Why this rule exists

The injected request session is where the framework's runtime controls live — the write guard, row scoping, and the audit hooks all ride on the session the framework hands out. A hand-constructed session or engine sits outside every one of those chokepoints by definition: its reads are unscoped, its writes are unaudited and unguarded, and it silently forks the app onto a second connection lifecycle.

## How Terp realises this

SessionDep injects the guarded request session; Session(...) / create_engine / sessionmaker construction in app code is refused.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-no-raw-session-construction: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? No — this is a property of the written source only; the build-time check is the control, by recorded decision.
- `build-time`: `terp.arch` — `check_no_raw_session_construction`
