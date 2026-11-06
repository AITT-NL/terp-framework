# `backend/no_adhoc_permission_literals`

**Modules reference typed authority objects, never bare permission strings**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/no_adhoc_permission_literals.json`.

## Why this rule exists

An authority named as a bare string is invisible to the control plane: it cannot be resolved against the app's declared registry, so a typo or a stale name silently grants nothing (or the wrong thing) instead of failing the build. Citing typed authority objects keeps every permission reference greppable and verifiable against the registry, and lets the runtime normalization chokepoint refuse anything unregistered.

## How Terp realises this

Role / Permission objects from the control-plane registry; requirement_from raises TypeError on a bare string.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-no-adhoc-permission-literals: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? Yes — the framework also enforces this while the app runs (fail closed).
- `build-time`: `terp.arch` — `check_no_adhoc_permission_literals`
- `runtime`: `terp.core` — `requirement_from`
