# `backend/request_timestamps_carry_their_offset`

**A timestamp a client sends carries its UTC offset**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/request_timestamps_carry_their_offset.json`.

## Why this rule exists

A date and time without a UTC offset names no instant: ten in the morning is a different moment in every zone. Stored as if it were UTC, it puts a sender in any other zone off by that zone's offset, and nothing reports it. The published API contract already rules such a value out, since a date-time there is the RFC 3339 form, whose offset is required. So the request boundary refuses one, in a request body and in a declared filter, and the refusal names the fix. Reading a value without an offset as UTC, for a sender known to send UTC without saying so, is the one way around it, and it is an escape a person decides and a reviewer sees.

## How Terp realises this

Each reference to terp.core's NaiveMeansUtc is refused: by name under any alias, through the terp.core module (core.NaiveMeansUtc), or inside a quoted annotation. Taking it is the opt-out marker on that line. A plain datetime field on a BaseSchema needs nothing, and neither does a datetime query parameter forwarded to a declared filter: at run time the schema refuses a client's timestamp text without an offset as a 422 at the field, and the filter refuses a bound without one as a 400 that names it (ADR 0206). A NaiveMeansUtc the file defines itself is not the escape, since the boundary does not step aside for it.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-request-timestamps-carry-their-offset: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? Yes — the framework also enforces this while the app runs (fail closed).
- `build-time`: `terp.arch` — `check_request_timestamps_carry_their_offset`
- `runtime`: `terp.core` — `refuse_timestamps_without_an_offset`
- `runtime`: `terp.core` — `require_offset`
