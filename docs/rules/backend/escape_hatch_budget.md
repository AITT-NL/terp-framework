# `backend/escape_hatch_budget`

**Opt-out marker counts must exactly match the checked-in budget (a ratchet)**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/escape_hatch_budget.json`.

## Why this rule exists

The budget is a checked-in per-app object mapping each opt-out marker to its count. Actual usage must equal it exactly: a marker that rose needs a justified budget bump in the same change; one that dropped must be lowered to lock in the win; an unbudgeted marker must be added with a justified count. This keeps every secure-by-default opt-out visible, greppable, and governed.

## How Terp realises this

# arch-allow-<rule>: <reason> markers reconciled against the app's checked-in escape-hatch budget JSON (design §8). The rule carries no opt_out: governance cannot be waived by the mechanism it governs.

## If you really need an exception

There is none. This rule governs the escape-hatch mechanism itself,
so it cannot be waived by that mechanism.

## Enforcement

- Checked while the app runs? No — this is a property of the written source only; the build-time check is the control, by recorded decision.
- `build-time`: `terp.arch` — `check_escape_hatch_budget`
