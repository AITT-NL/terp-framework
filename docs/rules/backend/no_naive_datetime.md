# `backend/no_naive_datetime`

**Timestamps must be timezone-aware, never naive**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/no_naive_datetime.json`.

## Why this rule exists

A timestamp captured without a timezone silently assumes the process's local zone, so it cannot be stored, compared, or ordered correctly once more than one zone is involved — a classic source of off-by-hours bugs. Every timestamp the app produces must carry an explicit timezone (UTC), so the moment it names is unambiguous.

## How Terp realises this

datetime.utcnow() (deprecated, naive) and a bare datetime.now() (no tz) are refused; datetime.now(UTC) is the compliant, timezone-aware path.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-no-naive-datetime: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? No — this is a property of the written source only; the build-time check is the control, by recorded decision.
- `build-time`: `terp.arch` — `check_no_naive_datetime`
