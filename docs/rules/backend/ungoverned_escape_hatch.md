# `backend/ungoverned_escape_hatch`

**The fail-closed ungoverned-opt-out condition, as structured violations**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/ungoverned_escape_hatch.json`.

## Why this rule exists

An opt-out marker the governance contract does not honour is itself a violation, reported in-band as structured findings (one per marker line) rather than crashing the harness: a marker used with no escape-hatch budget governing it, and a marker whose missing justification means it never suppressed anything. Either way the fix is to govern the opt-out — add the budget and the reason — never to silently honour it.

## How Terp realises this

assert_app_clean raises on an ungoverned # arch-allow-* marker; ungoverned_marker_violations projects the budget-less condition and _apply_suppressions re-reports an unjustified marker under the same rule, for terp check --format json. The rule carries no opt_out: governance cannot be waived by the mechanism it governs.

## If you really need an exception

There is none. This rule governs the escape-hatch mechanism itself,
so it cannot be waived by that mechanism.

## Enforcement

- Checked while the app runs? No — this is a property of the written source only; the build-time check is the control, by recorded decision.
- `build-time`: `terp.arch` — `ungoverned_marker_violations`
