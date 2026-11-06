# `backend/no_mutable_default_args`

**No mutable default argument values**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/no_mutable_default_args.json`.

## Why this rule exists

A default argument value is evaluated once when the function is defined and then shared by every call that omits it, so a mutable default (a list, dict, or set) accumulates state across calls — a classic aliasing bug that leaks data between otherwise independent invocations. Default to a sentinel and build the container inside the body.

## How Terp realises this

A list, dict, or set literal used as a parameter default (positional or keyword-only) is refused; default to None and construct the container in the body when the argument is omitted.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-no-mutable-default-args: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? No — this is a property of the written source only; the build-time check is the control, by recorded decision.
- `build-time`: `terp.arch` — `check_no_mutable_default_args`
