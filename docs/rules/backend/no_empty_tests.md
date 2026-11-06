# `backend/no_empty_tests`

**Every test must assert a real outcome**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/no_empty_tests.json`.

## Why this rule exists

A test whose body is empty, is only a docstring or a bare pass, or asserts a constant that can never fail, passes unconditionally — it exercises nothing yet reports green, giving false confidence that the behaviour it names is covered. A test must drive real behaviour and assert a real result.

## How Terp realises this

A test_* function with an empty body, a lone pass, or a single assertion of a constant truthy value is refused. The scan covers every test_*.py file — the test tree the other source rules deliberately skip.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-no-empty-tests: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? No — this is a property of the written source only; the build-time check is the control, by recorded decision.
- `build-time`: `terp.arch` — `check_no_empty_tests`
