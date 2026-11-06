# 0205 — A timestamp column stores an instant, as UTC, on every dialect

- **Status:** Accepted for building on 2026-11-06. The owner approved the follow-up
  [ADR 0204](0204-a-statistic-is-declared-on-the-service-like-a-filter.md) recorded; the
  choices below were made in the build and are the owner's to review, the two open questions
  first. Built in 0.37.0. An independent review of the first build found three
  runtime regressions and four claims the code did not support. Each is fixed below (see
  *What the review changed*). The owner decided both open questions on 2026-11-06, built in
  0.38.0: A by [ADR 0206](0206-a-timestamp-a-client-sends-carries-its-offset.md), and B in the
  rule's revision (see *Open questions*).
- **Date:** 2026-11-06.
- **Relates:** [ADR 0204](0204-a-statistic-is-declared-on-the-service-like-a-filter.md) (its
  known gap, which this closes), [ADR 0069](0069-verified-database-dialects-and-schema-direction.md)
  (the two dialects every answer must agree on),
  [ADR 0203](0203-the-rules-belong-to-the-framework-and-only-the-contracts-are-neutral.md) (the
  rules move into this framework, which decides where the rule's catalog prose lands), and the
  `no_naive_datetime` and `datetime_columns_are_timezone_aware` rules.

## Decision

`terp.core` gains `UtcDateTime`, a column type that stores an instant as UTC on every dialect.
It converts every datetime to UTC before it is bound, in a row and in a comparison alike, and
it reads every value back aware, in UTC. Every timestamp the framework declares uses it:

- `BaseTable`'s `created_at` and `updated_at`, and `SoftDeleteMixin`'s `deleted_at`;
- the timestamps of every capability's own tables;
- the migration record.

An app declares its own the same way, `Field(sa_type=UtcDateTime())`. The stored type is
unchanged, so adopting it needs no migration. `datetime_columns_are_timezone_aware` accepts it
and names it in its remedy, and `DateTime(timezone=True)` stays accepted. From 0.38.0 the rule
accepts only `terp.core`'s `UtcDateTime` (open question B, decided).

## Context

`DateTime(timezone=True)` means two different things. PostgreSQL's `TIMESTAMP WITH TIME ZONE`
stores an instant and converts on the way in. SQLite has no such type: the value's wall time
is written as text and its offset is dropped. So 10:00 in Amsterdam is stored as `10:00`. It
compares as later than 09:30 UTC though it is 09:00 UTC, and it reads back with no zone.

Measured on SQLite and PostgreSQL 16, with one row written at 10:00 in Amsterdam:

| Column type | Rows before 09:30 UTC, SQLite | PostgreSQL | Read back on SQLite |
|---|---|---|---|
| `DateTime(timezone=True)` | 0 | 1 | `2026-11-06 10:00:00`, no zone |
| `UtcDateTime` | 1 | 1 | `2026-11-06 09:00:00+00:00` |

The framework stamps UTC, so the timestamps it writes itself were stored right. Two things
still went wrong on SQLite:

- **Values from elsewhere.** A value a caller wrote in another zone was stored as that zone's
  wall time, off by its offset.
- **Comparison bounds.** Every bound in a comparison was compared as its wall time, so a bound
  in another zone was off by its offset too.

ADR 0204 met the first in its own steps and recorded it as a gap for every comparison. The
other half of the cost is in the code: four capabilities, the CLI and `terp.core`'s scheduler
each carry a helper that puts UTC back on a value read without a zone.

## Decisions

### 1. One type, over the type it stores as

`UtcDateTime` is a `TypeDecorator` over `DateTime(timezone=True)`. What it is given decides
what it does:

| Value | Bound as |
|---|---|
| A datetime with an offset | the same instant in UTC |
| A naive datetime | taken to be UTC as it stands |
| A plain date | its midnight in UTC, in a row and in a comparison |
| Anything else (the `timedelta` in `created_at + timedelta(days=30)`) | the impl's choice, an interval, as before |
| `None` | `NULL` |

It reads every value back aware, in UTC, and its `python_type` is `datetime`, which a
decorator does not answer on its own.

**A naive value is a change on PostgreSQL.** PostgreSQL used to read a naive value in the
session's time zone, which on a server whose zone is not UTC is an offset away from UTC.
Measured on a session in `Europe/Amsterdam`: the plain type stored a naive 10:00 as 09:00 UTC,
and this type stores it as 10:00 UTC, the meaning it already had on SQLite. A plain date moves
the same way, from the session's midnight to UTC's, and so does a comparison against either.

**A naive value is taken, not refused.** Refusing it at bind would be a 500 a client can cause,
because a bind cannot raise a typed error. `no_naive_datetime` does not prevent one either. It
refuses only `datetime.utcnow()` and a bare `datetime.now()`. A naive value built any other way
reaches the column as it is, and two of those ways read the host's own clock:
`datetime.fromtimestamp()` and `datetime.today()`. On a host whose zone is not UTC, that value
is stored off by the host's offset. So is a naive value a client sends from another zone, off
by the client's offset. Whether to refuse a naive value where it enters is open question A,
decided by ADR 0206: from 0.38.0 a request body and a declared filter refuse one.

### 2. A bound the type cannot hold is refused where it enters

An offset can carry a valid ISO string past the years a timestamp holds:
`0001-01-01T00:00:00+14:00` is a moment before year 1 in UTC. Converted at the bind, it raises
an overflow inside the driver call, a 500. Where the framework takes such a value from a caller,
it now refuses it with a 400 first:

- **The keyset cursor.** `decode_cursor` converts the position to UTC and refuses the overflow
  with the 400 it gives any malformed cursor. The position only ever meets `created_at`.
- **The declared filters.** `FilterField.condition` checks the bound and names the filter. It
  leaves the bound as given: a `UtcDateTime` column converts it, and an app's own plain column
  compares it as it always did.
- **A write.** `_save` maps the bind's overflow to a 400 and rolls the write back, so a create
  DTO carrying such a value is refused, not a 500.
- **A statistics window.** Year 1's first midnight in a zone east of UTC, and the step after
  31 December 9999, have no UTC instant. `aggregate` refuses the window.

Before this type, such a bound compared as its wall time. A `>` bound before year 1 matched
every row, so a request that answered 200 now answers 400. An app's own query that binds such
a value without going through these edges still gets a 500.

### 3. Every timestamp the framework declares, and any an app declares

The framework's own columns move to it in this release. A test sweeps every model a framework
package maps, and the migration record, and fails on a timestamp stored any other way. An
app's columns are its own. The rule accepts `UtcDateTime`, named or called, and its remedy and
the module guide show it. An app adopts it by changing the declaration, and the schema does not
change.

The base mixins are the exception to "an app's own pace". `created_at`, `updated_at` and
`deleted_at` are on every app table, so they move with the upgrade.

### 4. A revision says what is stored

Left to Alembic, an autogenerated revision writes the type as
`terp.core.base_models.UtcDateTime()`. That is a valid call, but the revision never imports the
name, so it fails when it runs. `terp migrate make` renders it as `sa.DateTime(timezone=True)`,
which is exactly what it stores. That keeps the revision plain SQLAlchemy, readable long after
the model that wrote it has changed. A schema diff sees no change on either dialect, because the
compiled type is the same.

## What does not change

- **Stored rows are not rewritten.** On SQLite, a value earlier written in a non-UTC zone now
  reads as UTC. It is still off by its offset, as it always compared. The framework's own
  stamps were UTC, so they are unaffected.
- **An aware value is stored on PostgreSQL as before.** Values read back are converted to UTC
  rather than to the session's zone, so a reader sees the same offset on both dialects. A naive
  value and a plain date are the exception, as decision 1 says.
- **The rule's runtime half stays deferred.** The catalog records a boot check over the mapped
  tables as `runtime.applicability: deferred`. This record does not ship it.
- **Most naive-read helpers stay.** The one-line helpers are no-ops on these columns now and
  harmless. Two branches existed only for a value SQLite read back without a zone: the
  service-account expiry check and the outbox backlog probe. The type makes them unreachable,
  so they are removed.

## Two-layer enforcement

| | Build time | Runtime |
|---|---|---|
| A timestamp column drops its zone | `datetime_columns_are_timezone_aware`, which accepts `UtcDateTime` and, until 0.38.0, `DateTime(timezone=True)` | deferred (the catalog's boot check) |
| An instant compares wrong on SQLite | until 0.38.0 none, because the rule accepted the plain type; from 0.38.0 the rule refuses it | `UtcDateTime`, for a column declared with it |
| App code builds a naive value | `no_naive_datetime`, for `utcnow()` and a bare `now()` only | none: the type takes it as UTC, a default and not a control |
| A client sends a naive value | from 0.38.0, `request_timestamps_carry_their_offset`, which governs the one way around | from 0.38.0, a `BaseSchema` body and a declared filter refuse it (ADR 0206) |
| A caller's bound overflows the type | none | `decode_cursor`, `FilterField`, `_save` and the statistics window refuse it with a 400 |
| A framework timestamp is declared the SQLite way | the sweep in `test_utc_datetime.py` | none |

## Open questions

Both were decided by the owner on 2026-11-06 and are built in 0.38.0.

- **A. Should a naive value be refused where it enters?** Yes, in a record of its own:
  [ADR 0206](0206-a-timestamp-a-client-sends-carries-its-offset.md). A request body built on
  `BaseSchema` refuses a client's timestamp text without an offset, as a 422 at the field, and a
  declared filter refuses a bound without one, as a 400. The contract does not change, because
  `format: date-time` already requires the offset. `NaiveMeansUtc` is the one way around, and a
  budgeted escape. As asked here, a naive value from a client in another zone was stored off by
  that client's offset.
- **B. Two compliant spellings, and a match on the name.** Both close in the rule's revision.
  `datetime_columns_are_timezone_aware` refuses `DateTime(timezone=True)` and
  `TIMESTAMP(timezone=True)`, naming `Field(sa_type=UtcDateTime())` as the replacement, which
  needs no migration. `UtcDateTime` counts only when it resolves to `terp.core`, so a class of
  that name that the file defines, or imports from anywhere else, is refused. As asked here,
  `DateTime(timezone=True)` stayed compliant though on SQLite it is the defect, and any name
  `UtcDateTime` passed.

## What the review changed

The first build was reviewed against the code before its pull request, and the review's
findings are folded in above:

- **Coercion.** The type compared every value through itself, so `created_at + timedelta(...)`
  and `created_at >= date(...)` raised `AttributeError`, on every app table's base timestamps.
  A date and a datetime now compare through the type, and anything else as the impl would.
- **Dates.** A plain date written into a column raised the same way. It is now UTC's midnight.
- **Overflow.** A crafted cursor or filter bound past year 1 or year 9999 was a 500. It is a 400
  at the edge (decision 2). A second pass found the same overflow in a write and in a statistics
  window, which were 500s too, and now also answer 400.
- **The filter's bound.** The first fix moved every aware filter bound to UTC. That changed the
  answer on an app's own plain column on SQLite, so the filter now only checks the range.
- **The API type.** A statistic over a `UtcDateTime` column was typed as anything in the API
  contract, because a decorator answers `object` for its Python type. It is `datetime` now, and
  a test types a figure over one.
- **Claims:** these were corrected above:
  - that `no_naive_datetime` refuses building a naive value;
  - that storage on PostgreSQL is unchanged for a naive value;
  - what Alembic would write without the hook;
  - the runtime column of the enforcement table;
  - the module guide's example, whose create DTO lacked the column it added;
  - that the overflowing bound had matched no rows. With rows present, it matched every one.
- **A test that could not fail offline.** The date test passed with the date branch removed on
  SQLite and on a UTC session. It now asserts the bind itself.

## Consequences

- The framework's timestamps compare and read back the same on both dialects, and the statistics
  seam's day steps count a late local instant on its own day on SQLite too.
- An app moves its own columns at its own pace. Declaring `UtcDateTime` changes no schema, and
  `terp migrate make` writes no revision for it.
- The catalog's `reference` for `backend/datetime_columns_are_timezone_aware` lists the
  spellings the rule accepts, and this one is not among them yet. The order is: this reaches
  framework main, then the reference and a compliant corpus case land, wherever the rules then
  live under ADR 0203.
- Upgrade notes:
  - An app that compared a framework timestamp on SQLite against a value in another zone now
    gets the instant's answer, which changes a test that encoded the old one.
  - On a PostgreSQL server whose session is not in UTC, a naive value or a plain date written to
    a framework timestamp is stored as UTC, not in the session's zone. A comparison against one
    shifts the same way.
  - A cursor, filter, write or statistics window whose datetime falls before year 1 or after
    year 9999 in UTC is a 400, where it used to answer as its wall time.
