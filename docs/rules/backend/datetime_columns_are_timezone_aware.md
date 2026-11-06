# `backend/datetime_columns_are_timezone_aware`

**A stored timestamp column records an instant, the same on every database**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/datetime_columns_are_timezone_aware.json`.

## Why this rule exists

A timestamp column declared without a timezone maps to a naive database type, which discards the zone of even a correctly-built aware value on the way in, so the moment a row records is ambiguous and ordering or comparison across zones is silently wrong. A column that keeps the zone on one database can still store the wall time on another, so the same row records a different instant depending on where it was written, and a test on one database proves nothing about the other. Every persisted timestamp column is declared with the framework's own timestamp type, which stores the instant as UTC on every database. This is the storage half of the hole whose in-memory half the naive-timestamp rule closes: capturing an aware value is worth nothing if the column cannot keep it.

## How Terp realises this

On a table model, a datetime (or datetime | None) field is refused unless its declaration names terp.core's UtcDateTime, called or as the class, through sa_type or sa_column: Field(sa_type=UtcDateTime()) or Field(sa_column=Column(UtcDateTime(), ...)). It counts imported from terp.core under any alias, or reached through the terp.core module (core.UtcDateTime). A UtcDateTime the file defines itself or imports from anywhere else is refused, since nothing holds it to storing UTC. DateTime(timezone=True) and TIMESTAMP(timezone=True), qualified or not, keep the zone on PostgreSQL and store the wall time on SQLite, so they are refused with the replacement named: the database column type is the same, so the change needs no migration (ADR 0205). A bare annotation, a Field() that never names the column type, and an explicit timezone=False are naive storage. Fields a table inherits from a mixin declared in the same file are in scope, since the column lands on the table either way. Classes no table inherits (DTOs, unrelated payloads) declare no columns, and migrations spell the column as the database sees it; both are out of scope.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-datetime-columns-are-timezone-aware: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## Enforcement

- Checked while the app runs? Not yet — a runtime control is planned; the gap is explicit and tracked.
- `build-time`: `terp.arch` — `check_datetime_columns_are_timezone_aware`
