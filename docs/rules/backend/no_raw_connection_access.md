# `backend/no_raw_connection_access`

**Modules never reach the raw DB connection / engine behind the session**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/no_raw_connection_access.json`.

## Why this rule exists

The runtime write guard covers the request session's own persistence methods, but the bound engine / connection the session exposes can issue data-modification statements directly, bypassing the audited chokepoint. A module must never reach for the session's underlying bind or connection; persist through the model's service so every write is audited. The escape is caught at the reach itself, and raw session / engine construction is separately banned by no_raw_session_construction — so an unrelated connect call on a domain object (a websocket / cache / search client) is deliberately not flagged.

## How Terp realises this

session.get_bind() / session.connection() calls are refused (ADR 0015, F3); BaseService is the audited write path, and WriteGuardedSession gates session.connection() at runtime.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-no-raw-connection-access: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? Yes — the framework also enforces this while the app runs (fail closed).
- `build-time`: `terp.arch` — `check_no_raw_connection_access`
- `runtime`: `terp.core` — `WriteGuardedSession`
