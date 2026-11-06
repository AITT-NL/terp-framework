# `frontend/no-raw-clipboard`

**Putting text on the clipboard goes through the stack's seam, not navigator.clipboard**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/frontend/eslint-boundaries/catalog/frontend/no-raw-clipboard.json`.

## Why this rule exists

navigator.clipboard is not the API its type describes. The DOM lib types it as always present, and it is absent outside a secure context — so on a plain-http origin that is not localhost, navigator.clipboard.writeText(...) is a property access on undefined. That throws a synchronous TypeError before any promise exists, which means a .catch on the call never runs and neither does a try wrapped around an await that was never reached. Nothing in the type system reports it, so the whole class is invisible to review and to a type check: the observable outcome is a control that does nothing and says nothing, found by a person clicking it in a deployment served over http. Every app that reaches for the API directly rediscovers this, which is what makes it a rule rather than a lesson. The rule is about the DEFECT, not about copying: the seam a conformant stack ships is expected to feature-detect the API, fall back where it is absent, and report a refusal rather than resolve as though it had worked.

## How Terp realises this

Any access to `navigator.clipboard` in app code is refused — the member expression, not merely a call, because `const c = navigator.clipboard` is the same throw one line earlier; the `window.`/`globalThis.` prefixed and computed (`navigator["clipboard"]`) spellings and the destructuring form (`const { clipboard } = navigator`) are refused with it, since each binds the same undefined under a different name. The reference stack ships `copyText` (the mechanism, callable anywhere) and `useCopyToClipboard` (adding the transient "copied" acknowledgement a control needs) from `@terpjs/react-core`; `copyText` resolves to `false` when the text did not reach the clipboard, so a caller that ignores a refusal has chosen to rather than never having been told.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
// terp-allow-no-raw-clipboard: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? No — this is a property of the written source only; the build-time check is the control, by recorded decision.
- `build-time`: `@terpjs/eslint-boundaries` — `BOUNDARY_SPEC.restrictRawClipboard`
