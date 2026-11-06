# `backend/no_manual_ownership_checks`

**Modules preserve structural row ownership and never reimplement it by hand**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/no_manual_ownership_checks.json`.

## Why this rule exists

Object-level authorization belongs to the platform's write boundary: user-owned rows retain their ownership declaration across request and background workflows, and a worker identity never becomes a blanket cross-owner authority. Application code must not compare, filter or assign the managed owner column, nor remove ownership merely to let unattended maintenance mutate every user's rows. Cross-owner maintenance requires a separately reviewed authority mechanism whose scope is explicit; ordinary background work remains subject to the same row ownership as interactive writes. Unlike the actor-stamp rule, a plain read of the owner column is refused too, and deliberately: a read is the first half of a hand-rolled per-row gate, and no static check can tell it from a read that only displays who owns the row.

## How Terp realises this

OwnedMixin declares ownership; BaseService stamps owner_id and apply_object_authz gates writes. create_app refuses a job-bearing ModuleSpec whose declared service model omits OwnedMixin. A custom object-authz predicate can be registered.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-no-manual-ownership-checks: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## What the check is not required to catch

A check precise enough to have no false positives has limits. This
rule's limits are recorded as data (its corpus's `RESIDUALS.json`), so
where detection ends is a statement rather than a guess:

- a ModuleSpec that omits `services=` is not required to be caught by the composition-time twin, which iterates the declared services

**These are not exemptions.** The rule governs those forms exactly as it
governs any other — a checker is simply not required to find them, so
review is the control there. The list only shrinks: closing one means
adding the corpus case that contracts it.

## Enforcement

- Checked while the app runs? Yes — the framework also enforces this while the app runs (fail closed).
- `build-time`: `terp.arch` — `check_no_manual_ownership_checks`
- `runtime`: `terp.core` — `apply_object_authz`
- `runtime`: `terp.core` — `validate_background_jobs_preserve_ownership`
