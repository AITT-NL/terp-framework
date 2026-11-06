# `backend/no_adhoc_config_decrypt`

**Sealed config is never decrypted ad hoc; one budgeted call site only**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/no_adhoc_config_decrypt.json`.

## Why this rule exists

A sealed configuration value stays opaque in app code: a module renders the masked form and never unseals a value itself. The single sanctioned decrypt site carries a justified opt-out marker counted against the app's escape-hatch budget. The runtime half is the decrypt chokepoint itself, which fails closed unless called from the one registered call site.

## How Terp realises this

mask_config renders sealed values (enc:v1:...); terp.core.secrets.decrypt_config fails closed unless called from the site registered via register_decrypt_call_site (design §5.4).

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-no-adhoc-config-decrypt: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? Yes — the framework also enforces this while the app runs (fail closed).
- `build-time`: `terp.arch` — `check_no_adhoc_config_decrypt`
- `runtime`: `terp.core` — `decrypt_config`
