# `backend/jobs_reference_catalog`

**Enqueued / declared jobs are typed catalog constants, never bare strings**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/jobs_reference_catalog.json`.

## Why this rule exists

Background work carries the same no-drift guarantee as the event bus: every job a module enqueues or declares is a typed definition from the control-plane catalog. The rule forbids a bare string (or an inline, ad hoc definition) wherever a job is named — the job argument of an enqueue call and the jobs list of the module manifest — so a job name can never drift in outside the catalog. The runtime half is the enqueue chokepoint, which rejects a job not registered in the active catalog.

## How Terp realises this

JobDefinition constants from the control-plane catalog, cited in enqueue(job=...) / ModuleSpec(jobs=[...]); the runtime half is terp.core.enqueue.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-jobs-reference-catalog: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? Yes — the framework also enforces this while the app runs (fail closed).
- `build-time`: `terp.arch` — `check_jobs_reference_catalog`
- `runtime`: `terp.core` — `enqueue`
