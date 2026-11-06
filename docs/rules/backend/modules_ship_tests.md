# `backend/modules_ship_tests`

**Every wired module ships at least one test of its own**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/modules_ship_tests.json`.

## Why this rule exists

The canonical module shape is five production files — models, schemas, service, router, manifest — and not one of them is a test, so a module could satisfy every structural rule in this Standard while shipping no tests at all. That is not a corner an application cuts by accident: a scaffolder that emits the canonical shape emits an untested module by default, and the gate then agrees with it. This rule closes the gap that no_empty_tests exposes — the Standard had an opinion about whether a test that exists can fail, and none about whether one exists. It asks only that the tests exist and are attributable to the module; whether they are any good is no_empty_tests and the application's own coverage gate.

## How Terp realises this

For every directory under modules/ that is a wired module (it ships a manifest or a mounted router — the same signal canonical_module_shape uses), the project's tests/ tree carries either a tests/<module>/ package containing at least one test_*.py, or a flat tests/test_<module>.py / tests/test_<module>_*.py. The per-module package is the canonical form and is what a scaffolder should emit; the flat form is recognised so that an application whose modules are in fact tested is not forced to justify them with a marker claiming they are not. The separator is required, so a module named as a prefix of another is not credited with its sibling's tests. Tests belong to the project's tests/ tree rather than the module directory, because a test that drives the composed application has to live where the application fixtures are; a reference checker resolves that tree beside the scanned root, and accepts one inside it so a corpus case can express the rule.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-modules-ship-tests: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? No — this is a property of the written source only; the build-time check is the control, by recorded decision.
- `build-time`: `terp.arch` — `check_modules_ship_tests`
