# `frontend/escape-hatch`

**Every opt-out marker is justified and governed by the budget ratchet**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/frontend/eslint-boundaries/catalog/frontend/escape-hatch.json`.

## Why this rule exists

The one opt-out is a justified inline marker naming the rule; an unjustified marker is itself an error, and marker counts must exactly match the app's checked-in escape-hatch budget so opt-outs stay visible and can only shrink.

## How Terp realises this

// terp-allow-<rule>: <reason> markers reconciled against the app's checked-in escape-hatch-budget.json (ADR 0059). The rule carries no opt_out: governance cannot be waived by the mechanism it governs.

## If you really need an exception

There is none. This rule governs the escape-hatch mechanism itself,
so it cannot be waived by that mechanism.

## Enforcement

- Checked while the app runs? No — this is a property of the written source only; the build-time check is the control, by recorded decision.
- `build-time`: `@terpjs/eslint-boundaries` — `terp/escape-hatch`
