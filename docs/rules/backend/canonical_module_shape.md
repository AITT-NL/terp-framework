# `backend/canonical_module_shape`

**Every wired module directory carries the canonical parts: models, schemas, service, router, manifest**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/canonical_module_shape.json`.

## Why this rule exists

Terp modules are uniform on purpose: the table lives in models, the DTOs in schemas, the logic in service, the routes in router, and the manifest declares the module — so the shape is predictable to discover and the other rules (response models, input caps, audited writes, the declared policy) have the surface they scan. A directory is treated as a module once it ships a manifest or a mounted router; it must then carry all of the canonical parts, and the rule names each missing one. Requiring the manifest is deliberate: a directory that ships a router with no manifest would otherwise be invisible to this rule and to modules_declare_policy (which only scans manifests), so it could mount a router with no declared policy unnoticed. A directory with neither signal (a partial or a shared-asset / helper directory) is left alone.

## How Terp realises this

modules/<name>/ carries models.py, schemas.py, service.py, router.py and module.py (the ModuleSpec manifest).

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-canonical-module-shape: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? No — this is a property of the written source only; the build-time check is the control, by recorded decision.
- `build-time`: `terp.arch` — `check_canonical_module_shape`
