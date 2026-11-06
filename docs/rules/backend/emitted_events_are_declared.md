# `backend/emitted_events_are_declared`

**A module emits only the events its manifest declares**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/emitted_events_are_declared.json`.

## Why this rule exists

The manifest's emits list is the module's published contract: it is what the control plane validates, what an operator reads to know what a module produces, and what another team subscribes against. An emit the manifest never declared makes that contract quietly untrue — the event really does go out, so nothing fails, while the document everyone reasons from says it cannot happen. The rule compares every event constant an emit call or lifecycle event map names inside a module package against that module's declared emits.

## How Terp realises this

ModuleSpec(emits=[...]) in modules/<name>/module.py, compared against emit(event=...) and LifecycleEventMap(created=/updated=/deleted=...) references in the same module package.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-emitted-events-are-declared: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? No — this is a property of the written source only; the build-time check is the control, by recorded decision.
- `build-time`: `terp.arch` — `check_emitted_events_are_declared`
