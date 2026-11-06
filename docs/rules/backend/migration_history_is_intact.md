# `backend/migration_history_is_intact`

**Each migration history is one unbroken chain from a single first revision**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/migration_history_is_intact.json`.

## Why this rule exists

A revision whose parent is missing, or a second revision claiming to start the history, means an already-authored migration was deleted or replaced rather than built upon. Every database that applied the removed revision then becomes unupgradable, and no schema-drift check can see it: a database rebuilt from the rewritten history is perfectly consistent with the models, so the build stays green while every provisioned environment is stranded. New schema changes are added on top of the existing chain.

## How Terp realises this

Within each non-empty migrations/versions directory, exactly one revision must declare no parent; every other revision's declared parent (one id, or each id of a merge revision's tuple) must name a revision defined in that same directory, and every revision must be reachable from that first revision (no cycles or disconnected chains).

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-migration-history-is-intact: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? No — this is a property of the written source only; the build-time check is the control, by recorded decision.
- `build-time`: `terp.arch` — `check_migration_history_is_intact`
