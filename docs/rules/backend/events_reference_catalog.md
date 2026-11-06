# `backend/events_reference_catalog`

**Emitted / subscribed events are typed catalog constants, never bare strings**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/events_reference_catalog.json`.

## Why this rule exists

The event bus carries the same no-drift guarantee as the permission model: every event a module emits or subscribes to is a typed definition from the control-plane catalog. The rule forbids a bare string (or an inline, ad hoc definition) wherever an event is named — the event argument of an emit call, the argument of a subscribe decorator, the emits / subscribes lists of the module manifest, and the lifecycle event map — so an event name can never drift in outside the catalog.

## How Terp realises this

EventDefinition constants from the control-plane catalog, cited in emit(...) / subscribe(...) / ModuleSpec(emits=..., subscribes=...) / LifecycleEventMap(...); the runtime half is terp.core.emit.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-events-reference-catalog: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? Yes — the framework also enforces this while the app runs (fail closed).
- `build-time`: `terp.arch` — `check_events_reference_catalog`
- `runtime`: `terp.core` — `emit`
