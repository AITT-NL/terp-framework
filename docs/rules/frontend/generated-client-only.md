# `frontend/generated-client-only`

**All network egress goes through the generated, typed client**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/frontend/eslint-boundaries/catalog/frontend/generated-client-only.json`.

## Why this rule exists

Raw fetch / XMLHttpRequest / WebSocket / EventSource (and navigator.sendBeacon) bypass the app's single audited, typed egress path. One client means one place for auth, errors, and contract types. The refused globals and member calls are declared in restricted-surface.json (restrictedGlobals, restrictedMemberCalls).

## How Terp realises this

useTerpClient() + unwrap from @terpjs/react-core for request/response; useRealtimeChannel() from @terpjs/react-core for typed SSE/WebSocket subscriptions (one-use ticket minted through the generated client).

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
// terp-allow-generated-client-only: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## What the check is not required to catch

A check precise enough to have no false positives has limits. This
rule's limits are recorded as data (its corpus's `RESIDUALS.json`), so
where detection ends is a statement rather than a guess:

- egress through receivers other than `window`/`globalThis` (`self.fetch`) is not required

**These are not exemptions.** The rule governs those forms exactly as it
governs any other — a checker is simply not required to find them, so
review is the control there. The list only shrinks: closing one means
adding the corpus case that contracts it.

## Enforcement

- Checked while the app runs? No — this is a property of the written source only; the build-time check is the control, by recorded decision.
- `build-time`: `@terpjs/eslint-boundaries` — `BOUNDARY_SPEC.restrictedGlobals`
