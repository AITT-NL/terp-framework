# `backend/no_blocking_sleep`

**Never block the thread with a synchronous sleep**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/no_blocking_sleep.json`.

## Why this rule exists

A synchronous sleep parks the thread that is serving the request or running the job, so the whole worker sits idle and the pool starves under load. Waiting must yield the thread — poll with an awaitable, schedule a delayed job, or let the runtime back off — never freeze it.

## How Terp realises this

A call to the standard library's time.sleep() is refused; use a non-blocking wait or a scheduled job.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-no-blocking-sleep: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? No — this is a property of the written source only; the build-time check is the control, by recorded decision.
- `build-time`: `terp.arch` — `check_no_blocking_sleep`
