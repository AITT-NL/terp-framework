# `backend/no_adhoc_background_runtime`

**App modules don't import a background engine / runtime directly — only adapter caps do**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/no_adhoc_background_runtime.json`.

## Why this rule exists

Background work (a scheduled sync, an export, a webhook) goes through the typed enqueue chokepoint and the context-binding kernel runner, so the engine that actually runs it stays a composition-root choice wired into an opt-in adapter capability, never an import baked into domain code. The rule forbids importing broker / scheduler engines (and a raw thread- or process-execution construct, or a bare import that can reach one) anywhere in an app module; an explicit synchronization primitive is a correctness tool, not background execution, and stays allowed. The constructive counterpart is the jobs seam itself: every job runs through the enqueue chokepoint and the active queue, so an adapter swap never touches a call site. An adapter capability legitimately imports its engine under a budgeted opt-out marker.

## How Terp realises this

terp.core.enqueue + the active JobQueue are the sanctioned seam; Celery / Azure Service Bus / Redis / APScheduler imports and threading/multiprocessing execution constructs (Thread, Process, pools) are refused, while primitives like RLock stay allowed.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-no-adhoc-background-runtime: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? No — this is a property of the written source only; the build-time check is the control, by recorded decision.
- `build-time`: `terp.arch` — `check_no_adhoc_background_runtime`
