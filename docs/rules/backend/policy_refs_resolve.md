# `backend/policy_refs_resolve`

**Every typed authority a policy cites resolves in the app's authority registry**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/policy_refs_resolve.json`.

## Why this rule exists

The build-time half of control-plane registry resolution: boot validation already refuses an undeclared authority at runtime; this rule catches the same drift at the gate, before the app ever boots. Any reference that traces to the app's authority registry — via a module alias or a name imported from the registry — must name something the registry actually declares. References the scan cannot trace to the registry (kernel default roles, locally built objects) are left to the runtime check, so the rule stays precise, never heuristic.

## How Terp realises this

control_plane/permissions.py is the registry; aliased references like perms.BILLING_READ must resolve there, kernel defaults like Roles.EDITOR are left to ControlPlane.validation_errors at boot.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-policy-refs-resolve: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? Yes — the framework also enforces this while the app runs (fail closed).
- `build-time`: `terp.arch` — `check_policy_refs_resolve`
- `runtime`: `terp.core` — `validation_errors`
