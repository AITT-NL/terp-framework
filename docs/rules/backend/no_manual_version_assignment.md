# `backend/no_manual_version_assignment`

**The optimistic-concurrency token is never assigned by hand**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/no_manual_version_assignment.json`.

## Why this rule exists

Every row carries an integer concurrency token that the persistence layer increments on each update and matches against the value the caller loaded, so two writers racing on the same row cannot silently clobber each other. Writing that token by hand does not fail — it overwrites the loaded value with the caller's own, so the concurrency check ends up comparing the row against itself and a lost update slips through undetected. Application code must never assign the token; the persistence layer owns it end to end.

## How Terp realises this

db_obj.version = data.version, row.version += 1, and setattr(db_obj, "version", ...) are refused; the update seam bumps and checks the token, so application code leaves it untouched.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-no-manual-version-assignment: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? No — this is a property of the written source only; the build-time check is the control, by recorded decision.
- `build-time`: `terp.arch` — `check_no_manual_version_assignment`
