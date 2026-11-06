# `backend/no_adhoc_logging_config`

**App code never configures logging globally; redaction is centralized**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/no_adhoc_logging_config.json`.

## Why this rule exists

Structured logging plus its redaction is installed once, centrally, at composition: secrets, recognised by name and by shape, and personal data, recognised only where a model declares the field personal, since an undeclared address has no shape to find. A module that re-points the global logging configuration itself can silently bypass the central redaction filter.

## How Terp realises this

configure_logging (called by create_app) installs the redacting handlers; logging.basicConfig / dictConfig / fileConfig calls in app modules are refused.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-no-adhoc-logging-config: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? No — this is a property of the written source only; the build-time check is the control, by recorded decision.
- `build-time`: `terp.arch` — `check_no_adhoc_logging_config`
