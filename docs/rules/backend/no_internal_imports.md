# `backend/no_internal_imports`

**Modules import only the platform's public surface, never its internal namespaces**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/no_internal_imports.json`.

## Why this rule exists

The public surface is the platform's contract: it is documented, versioned, and stable. An internal namespace is free to move or change shape at any release, and it exposes seams (raw session plumbing, guard internals) whose direct use bypasses the framework's controls — so a module that reaches into it is coupled to undocumented internals and can silently sidestep the secure defaults.

## How Terp realises this

Import from the terp.core public surface; terp.core._internal imports are refused.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-no-internal-imports: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? No — this is a property of the written source only; the build-time check is the control, by recorded decision.
- `build-time`: `terp.arch` — `check_no_internal_imports`
