# `backend/public_modules_are_read_only`

**A public (unauthenticated) module must not expose a mutating route**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/public_modules_are_read_only.json`.

## Why this rule exists

A public policy drops authentication for the whole module, so a mutating route under it is an unauthenticated write — almost always an accident, and the broken-access-control footgun the deny-by-default posture exists to prevent. A genuinely public write (a sign-up / contact form / webhook receiver) is rare and deliberate, so it stays available through the governed escape hatch: a justified opt-out marker ratcheted by the escape-hatch budget, making the unauthenticated write visible and budgeted rather than silent. Gate the writes behind a policy with a write role, or justify the public write explicitly. The runtime half is the boot refusal of a public module that exposes a mutating route unless its policy opts in explicitly with a reason — each layer carries its own justified opt-out.

## How Terp realises this

Policy.public(reason=...) declares the public module; create_app -> _validate_public_modules_read_only refuses public writes unless the policy opts in via Policy.public_write(reason=...).

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-public-modules-are-read-only: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? Yes — the framework also enforces this while the app runs (fail closed).
- `build-time`: `terp.arch` — `check_public_modules_are_read_only`
- `runtime`: `terp.core` — `validate_public_modules_read_only`
