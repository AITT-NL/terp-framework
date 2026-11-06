# `frontend/no-raw-random-uuid`

**Minting a UUID goes through the stack's seam, not crypto.randomUUID**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/frontend/eslint-boundaries/catalog/frontend/no-raw-random-uuid.json`.

## Why this rule exists

crypto.randomUUID is not the API its type describes. The DOM lib declares it unconditionally on the Crypto interface, and it exists only in a secure context -- so on a plain-http origin that is not localhost, calling it is a call on undefined and throws a synchronous TypeError. Nothing in the type system reports it, and neither does a test run: localhost IS a secure context, so the whole class is invisible to the type checker, to review and to CI at once, and surfaces only in a deployment. What makes it a rule rather than a lesson is that a conformant stack routes applications into it: an idempotency contract keyed on a CLIENT-generated request key means an app adding retry-safety reaches for exactly this method, and a stack whose default deployment topology publishes plain http puts that app in an insecure context by default. The rule is about the DEFECT, not about identifiers: the seam a conformant stack ships is expected to feature-detect, and to fall back to a source of cryptographic randomness that is NOT secure-context-gated rather than to a weaker one -- a value standing in for an idempotency key or a record id is one a collision corrupts, so silently reducing its entropy to keep a call site quiet is a worse failure than the throw.

## How Terp realises this

Any access to `crypto.randomUUID` in app code is refused -- the member expression, not merely a call, because `const gen = crypto.randomUUID` is the same broken binding one line earlier; the `window.`/`globalThis.`/`self.` prefixed and computed (`crypto["randomUUID"]`) spellings and the destructuring form (`const { randomUUID } = crypto`) are refused with it. `crypto.getRandomValues` is deliberately untouched: it is not secure-context-gated, it is not this defect, and the seam is built on it. The reference stack ships `randomUuid` from `@terpjs/react-core`, which uses the native generator where it exists and assembles the same v4 from `getRandomValues` where it does not, so the entropy is identical either way; with no `crypto` at all it throws `RandomUuidUnavailableError` rather than falling back to `Math.random`.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
// terp-allow-no-raw-random-uuid: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? No — this is a property of the written source only; the build-time check is the control, by recorded decision.
- `build-time`: `@terpjs/eslint-boundaries` — `BOUNDARY_SPEC.restrictRawRandomUuid`
