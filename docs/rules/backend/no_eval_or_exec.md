# `backend/no_eval_or_exec`

**Never execute a string as code**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/no_eval_or_exec.json`.

## Why this rule exists

Turning a runtime string into executed code is a code-injection hole: any value an attacker can influence on its way into the evaluator becomes arbitrary code the process runs. There is no safe in-app use — parse the data into a structure, dispatch on a lookup table, or import a real module instead of evaluating text.

## How Terp realises this

Calls to the eval() and exec() builtins are refused. The scan covers the whole importable tree — including tests and migrations — because any Python that runs is in scope.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-no-eval-or-exec: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? No — this is a property of the written source only; the build-time check is the control, by recorded decision.
- `build-time`: `terp.arch` — `check_no_eval_or_exec`
