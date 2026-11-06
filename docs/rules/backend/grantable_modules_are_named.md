# `backend/grantable_modules_are_named`

**A module that accepts a role of its own says what to call it**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/grantable_modules_are_named.json`.

## Why this rule exists

A module may opt into per-module roles, which lets an administrator give one person a higher tier inside that module and nowhere else. The screen that offers the choice renders one strip per such module, headed by the declared label — and that label is the only text about the module a reader ever sees there. Headed by an identifier instead, the strip asks someone to hand out authority over something the interface has not named. The declaration is required at the point of opting in rather than defaulted from the module's own name, because a name chosen to be imported is rarely a name chosen to be read.

## How Terp realises this

modules/<name>/module.py declares ModuleSpec(access=ModuleAccess(label=..., assignable=True)); ModuleAccess enforces the pairing as a constructor invariant.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-grantable-modules-are-named: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? Yes — the framework also enforces this while the app runs (fail closed).
- `build-time`: `terp.arch` — `check_grantable_modules_are_named`
- `runtime`: `terp.core` — `ModuleAccess`
