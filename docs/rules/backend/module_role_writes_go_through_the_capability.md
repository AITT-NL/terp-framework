# `backend/module_role_writes_go_through_the_capability`

**Per-module assignments are reached through the capability, never the table**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/module_role_writes_go_through_the_capability.json`.

## Why this rule exists

An assignment is a row saying a subject holds a tier inside a module, and the service that writes it is where two things happen: the audit entry is emitted, and the assignment is refused when the declarations cannot support it — a module that administers the platform's own authority, a module that never opted in, a tier the application's ladder does not declare. A row written around that service is not a more permissive assignment; it is one that can never take effect, and whoever wrote it will believe the person is authorized until the moment they are not. A plain read of the table is refused on the same footing as hand-rolled row ownership: a read is the first half of a per-module gate written by hand, and no static check can tell it from a read that only displays a tier. What a subject holds already has an answer that carries its provenance with it.

## How Terp realises this

ModuleRoleService.assign / revoke / highest_rank, the access capability's own routes, or the operator command; never the ModuleRole model directly.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-module-role-writes-go-through-the-capability: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? Yes — the framework also enforces this while the app runs (fail closed).
- `build-time`: `terp.arch` — `check_module_role_writes_go_through_the_capability`
- `runtime`: `terp.capabilities.access` — `validate_assignment`
