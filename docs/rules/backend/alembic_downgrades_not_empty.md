# `backend/alembic_downgrades_not_empty`

**A migration's downgrade must reverse the change, not be an empty stub**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/alembic_downgrades_not_empty.json`.

## Why this rule exists

A migration that leaves its downgrade step empty (a bare no-op with no operations) cannot be rolled back: reversing the revision silently leaves the schema mismatched instead of restoring the previous state. Each migration's downgrade must either perform the reverse operations or, for a deliberately irreversible step, carry a comment explaining why the no-op is intentional.

## How Terp realises this

In each revision file under migrations/versions, a downgrade function whose body (after any docstring) is a lone pass / ellipsis or is empty, with no explanatory comment, is flagged; a reverse operation or an in-body '#' comment clears it. That source check sees only emptiness. The reference stack pairs it with an EXECUTED rehearsal a consuming project runs on a scratch database — upgrade to head, downgrade to base, check every history emptied and nothing was left behind, upgrade again, compare the schema read from the database's own catalogue — which is what catches a downgrade that cannot run and one that does not undo what it did.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-alembic-downgrades-not-empty: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? No — this is a property of the written source only; the build-time check is the control, by recorded decision.
- `build-time`: `terp.arch` — `check_alembic_downgrades_not_empty`
- `build-time`: `terp.migrations` — `assert_migrations_reverse_cleanly`
