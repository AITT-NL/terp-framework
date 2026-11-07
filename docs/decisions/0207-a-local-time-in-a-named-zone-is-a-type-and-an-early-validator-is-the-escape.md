# 0207 — A local time in a named zone is a type, and an early validator on a timestamp is the escape

- **Status:** Accepted on 2026-11-07. The owner decided it on 2026-11-06, as the open question
  of [ADR 0206](0206-a-timestamp-a-client-sends-carries-its-offset.md) on an app's own
  validator that runs first, on the recommendation that record keeps under *Open*. Built in
  0.39.0 (unreleased).
- **Date:** 2026-11-07.
- **Relates:** [ADR 0206](0206-a-timestamp-a-client-sends-carries-its-offset.md) (the refusal
  of timestamp text without an offset, `NaiveMeansUtc`, and the rule this extends),
  [ADR 0205](0205-a-timestamp-column-stores-an-instant-as-utc.md) (the column that stores an
  instant as UTC), and [ADR 0059](0059-strict-frontend-boundary-and-escape-hatch-budget.md)
  (no modes: the one way around is a budgeted escape).

## Decision

`LocalTimeIn`, from `terp.core`, reads a timestamp sent as the wall time of a named zone:
`Annotated[datetime, LocalTimeIn("Europe/Amsterdam")]`. A value without a UTC offset is read as
a local time in that zone, and one with an offset is the instant it names. Either way it
arrives as an instant, aware and in UTC. A wall time the clocks skip in the zone, or repeat, is
refused, since it names no instant or two. The zone names the instant, so the type is no escape.

What is the escape is an app's own validator that reads a timestamp's text before its type
does. The `request_timestamps_carry_their_offset` rule now counts a `before`, `wrap` or `plain`
validator on a timestamp field where it is declared, with the marker and budget `NaiveMeansUtc`
takes.

## Context

ADR 0206 refuses timestamp text without an offset at the timestamp type. An app's own validator
in `before`, `wrap` or `plain` mode runs in front of that type, and of the refusal, so it sees
the text first. It can read a time with no offset in a zone of its own choosing, and nothing at
run time can tell that reading from the client's.

The same code is how an app takes a legitimate input today: the wall time of a zone the app
knows, such as a booking form for a venue in Amsterdam. While the two were the same code, the
rule could not count one without refusing the other. The owner decided on 2026-11-06 to give
the legitimate case a framework type, and then to count the validator.

## Decisions

### 1. `LocalTimeIn(zone)` reads the wall time of a named zone as the instant it names

Declare it on a field or a query parameter as `Annotated[datetime, LocalTimeIn(zone)]`, and an
optional one as that type `| None`. It reads:

- a value without a UTC offset as a local time in the zone: `2026-11-06T10:00` in
  `Europe/Amsterdam` is `2026-11-06T09:00:00Z`, and `2026-07-01T10:00` is `08:00` UTC;
- a bare date as its midnight in the zone;
- a value with an offset, and a Unix time, as the instant it names;
- a `datetime` object the same way as text, since what the type means does not depend on who
  built the value.

The value arrives aware and in UTC, so a declared filter takes it and `UtcDateTime` stores it
as it is. Text that reads as no date and time keeps the `datetime` type's own error.

The zone is the app's, declared on the field, as a filter declares the zone whose day it is
(ADR 0206, decision 3); the caller does not send it. A client that knows the person's own zone
sends the offset, as `DateTimeInput` does. A declaration is checked when it is made: a zone the
server does not know raises a `ValueError` that names an IANA zone as the fix, and `LocalTimeIn`
on anything but a `datetime` raises a `TypeError` that spells the declaration.

### 2. A wall time the clocks skip or repeat is refused

A wall time that does not happen in the zone, because the clocks skip it, names no instant. One
that happens twice, because they repeat it, names two. Both are a 422 at the value's place:

- `local_time_skipped`: *2026-03-29T02:30:00 does not happen in Europe/Amsterdam, where the
  clocks skip it; send a time that happens there, or one with its UTC offset*
- `local_time_repeated`: *2026-10-25T02:30:00 happens twice in Europe/Amsterdam, where the
  clocks repeat it; send it with its UTC offset, 2026-10-25T02:30:00+02:00 or
  2026-10-25T02:30:00+01:00*

`DateTimeInput` chooses instead: it moves a skipped time forward past the gap and takes the
earlier of a repeated one. It can, because a person sees the time it shows and can change it.
The server reads text from any sender and cannot ask, and a guess here is the error ADR 0206
refuses. A sender that meant one of the two sends its offset.

### 3. It is no escape, and its contract is a `datetime`'s

A `BaseSchema` leaves a `LocalTimeIn` node as the type built it. The walk knows the node by its
reader, an instance of the type, as it knows the escape's node by its function. So the refusal
does not run in front of it, and the fields beside it are judged as before. The rule does not
count it.

Its JSON schema is a `datetime`'s, `format: date-time`, as `NaiveMeansUtc`'s is. The contract
describes what a client should send, an instant with its offset, and the type takes that too. A
field that adopts it publishes what a plain `datetime` field publishes.

### 4. An app's own early validator on a timestamp is the escape

The rule counts each of these where it is declared:

- a `BeforeValidator`, `WrapValidator` or `PlainValidator` in an `Annotated` type that reads a
  timestamp, or a name bound to one. That includes `datetime`, `AwareDatetime` and Pydantic's
  other datetime types, under any alias the file binds, in a union, a list or a quoted
  annotation. A type alias is counted where it is spelled.
- a `field_validator` in `before`, `wrap` or `plain` mode, or Pydantic 1's `validator` with
  `pre=True`, on a field its class declares as a timestamp, or a base the same file defines. The
  field may be named, matched by `"*"`, or given as a field name or a mode the file computes,
  which the rule cannot read and so counts.

It does not count:

- an after validator, which sees the instant the type made;
- a validator on a field that is no timestamp; a `date` is a day;
- a validator of the whole model, which sees the body rather than a field. ADR 0206 recorded
  that counting it would mostly be noise.

A use stands when its line, or the line above, carries
`# arch-allow-request-timestamps-carry-their-offset: <reason>`, which the app's
`escape-hatch-budget.json` counts. The corpus records three residuals: a timestamp field a base
in another module declares, a model validator, and a validator a schema only gets at run time.

### 5. Two layers

The runtime half is still ADR 0206's refusal. An early validator runs in front of it, so at run
time its reading of a time without an offset looks like the client's, and the build-time half is
where it is seen. The catalog entry's runtime applicability stays `required`, citing the same
two controls.

## What does not change

- **An app with neither** an early validator on a timestamp nor the new type.
- **`NaiveMeansUtc`**, the escape for a sender known to send UTC, and its marker.
- **The contract.** Decision 3 publishes what a `datetime` publishes.
- **`DateTimeInput` and the frontend rule.** A form still sends an instant. A field that sends
  the wall time of a named zone keeps its `datetime-local` control with that rule's marker, and
  the API reads it with `LocalTimeIn`.

## Consequences

- An app with an early validator on a timestamp field fails the gate. It takes `LocalTimeIn`
  where the validator read the wall time of a known zone, an after validator where it only
  checked the instant, or the marker and a budget entry where it must keep reading the text.
- Two new error types reach a client: `local_time_skipped` and `local_time_repeated`.
- ADR 0206's other two 0.39.0 items remain: the startup check of a request body that is not a
  `BaseSchema`, and of a plain timestamp route parameter.
