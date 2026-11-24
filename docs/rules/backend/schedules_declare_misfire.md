# `backend/schedules_declare_misfire`

**A schedule says what a missed tick becomes**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/schedules_declare_misfire.json`.

## Why this rule exists

A tick that fell due while no scheduler ran either runs once, late, or is skipped, and which is right is a property of the work that only its author knows: an hourly snapshot taken late is still worth having, a reminder sent for an hour that has passed is not. So a schedule's definition declares it, and one that does not is refused where it is written. Without it the definition fails as the control plane is imported, before the app asks any other question at its start, so the gate names every such definition together with every other finding instead of a start naming them one at a time.

## How Terp realises this

A call to ScheduleDefinition(...) without misfire= is refused: by that name, by a name the file imports it under from terp.core or terp.core.scheduling, and as an attribute (core.ScheduleDefinition(...)). Pass misfire=Misfire.RUN_ONCE or misfire=Misfire.SKIP (ADR 0191). A call that passes keywords with ** may carry it, so it is not read as missing it.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-schedules-declare-misfire: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## What the check is not required to catch

A check precise enough to have no false positives has limits. This
rule's limits are recorded as data (its corpus's `RESIDUALS.json`), so
where detection ends is a statement rather than a guess:

- a call that passes keywords with ** is not read as missing misfire=, since the mapping may carry it: the definition itself refuses one that does not, as the control plane is imported
- a name bound to ScheduleDefinition by an assignment (Schedule = ScheduleDefinition) rather than an import is not followed: the definition itself refuses a call through it that omits misfire=

**These are not exemptions.** The rule governs those forms exactly as it
governs any other — a checker is simply not required to find them, so
review is the control there. The list only shrinks: closing one means
adding the corpus case that contracts it.

## Enforcement

- Checked while the app runs? Yes — the framework also enforces this while the app runs (fail closed).
- `build-time`: `terp.arch` — `check_schedules_declare_misfire`
- `runtime`: `terp.core` — `ScheduleDefinition`
