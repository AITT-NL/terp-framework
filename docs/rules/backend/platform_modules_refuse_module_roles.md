# `backend/platform_modules_refuse_module_roles`

**A module that hands authority out never accepts a role of its own**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/platform_modules_refuse_module_roles.json`.

## Why this rule exists

Per-module roles refine the role ladder; they must not offer a way around it. A module that can create a grant or a per-module assignment holds the authority that confers every other authority, so a per-module administrator there could grant themselves anything, everywhere — while the rung that allowed it looks like a narrow one, scoped to a single module. Such a module declares outright that it is never per-module assignable, and declares why, so the refusal is legible to whoever reads the access surface rather than being an absence they have to notice. The check is deliberately syntactic: holding the service is the trigger, with no attempt to decide whether a particular call site only reads, because a read is the first half of a write and nothing static can tell a module that lists grants from one about to create one.

## How Terp realises this

ModuleAccess.platform_only(reason=...) on the ModuleSpec of any module holding AccessService or ModuleRoleService; the platform's own users / groups / access / audit capabilities each declare it.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-platform-modules-refuse-module-roles: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? No — this is a property of the written source only; the build-time check is the control, by recorded decision.
- `build-time`: `terp.arch` — `check_platform_modules_refuse_module_roles`
