# `backend/modules_declare_policy`

**Every module manifest declares an access policy**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/modules_declare_policy.json`.

## Why this rule exists

The deny-by-default posture hangs on the declaration: composition mounts a module's routes behind the guard its declared policy configures, so a module without one has no stated authority model at all — there is nothing to authorize against, and the framework refuses to guess. Requiring the declaration in the manifest keeps every module's access decision explicit, reviewable, and in one predictable place.

## How Terp realises this

modules/<name>/module.py declares ModuleSpec(policy=Policy(...)); create_app mounts the router behind the guard built from it (build_guard).

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-modules-declare-policy: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? Yes — the framework also enforces this while the app runs (fail closed).
- `build-time`: `terp.arch` — `check_modules_declare_policy`
- `runtime`: `terp.core` — `build_guard`
