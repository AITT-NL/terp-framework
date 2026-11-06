# `backend/no_print`

**Emit diagnostics through the logger, never a bare print**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/no_print.json`.

## Why this rule exists

Printing straight to standard output bypasses log levels, structure, and routing, so the message escapes the platform's logging pipeline and cannot be filtered, correlated, or shipped to a sink. Every diagnostic must go through the structured logger so it carries a level and is captured.

## How Terp realises this

A call to the print() builtin is refused; obtain a logger and call it at the appropriate level.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-no-print: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? No — this is a property of the written source only; the build-time check is the control, by recorded decision.
- `build-time`: `terp.arch` — `check_no_print`
