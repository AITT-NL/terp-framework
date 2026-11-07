# 0207 — A local time in a named zone is a type, and an early validator on a timestamp is the escape

- **Status:** Accepted on 2026-11-07. The owner decided it on 2026-11-06, as the open question
  of [ADR 0206](0206-a-timestamp-a-client-sends-carries-its-offset.md) on an app's own
  validator that runs first, on the recommendation that record keeps under *Open*. Built in
  0.39.0 (unreleased). An independent review of the first build changed it (see *What the
  review changed*).
- **Date:** 2026-11-07.
- **Relates:** [ADR 0206](0206-a-timestamp-a-client-sends-carries-its-offset.md) (the refusal
  of timestamp text without an offset, `NaiveMeansUtc`, and the rule this extends),
  [ADR 0205](0205-a-timestamp-column-stores-an-instant-as-utc.md) (the column that stores an
  instant as UTC), and [ADR 0059](0059-strict-frontend-boundary-and-escape-hatch-budget.md)
  (no modes: the one way around is a budgeted escape).

## Decision

`LocalTimeIn`, from `terp.core`, reads a timestamp sent as the wall time of a place:
`Annotated[datetime, LocalTimeIn("Europe/Amsterdam")]`. A value without a UTC offset is read as
a local time in that zone, and one with an offset is the instant it names. Either way it
arrives as an instant, aware and in UTC. A wall time the clocks skip in the zone, or repeat, is
refused, since it names no instant or two. A place names the instant, so the type is no escape,
and it is held to that: a zone that names no place, such as UTC under any name, is refused when
declared, and the type cannot be subclassed or changed.

What is the escape is an app's own validator that reads a timestamp's text before its type
does. The `request_timestamps_carry_their_offset` rule now counts a `before`, `wrap` or `plain`
validator on a timestamp field where it is declared, and a type that carries one at each use,
with the marker and budget `NaiveMeansUtc` takes.

## Context

ADR 0206 refuses timestamp text without an offset at the timestamp type. An app's own validator
in `before`, `wrap` or `plain` mode runs in front of that type, and of the refusal, so it sees
the text first. It can read a time with no offset in a zone of its own choosing, and nothing at
run time can tell that reading from the client's.

The same code is how an app takes a legitimate input today: the wall time of a place the app
knows, such as a booking form for a venue in Amsterdam. While the two were the same code, the
rule could not count one without refusing the other. The owner decided on 2026-11-06 to give
the legitimate case a framework type, and then to count the validator.

## Decisions

### 1. `LocalTimeIn(zone)` reads the wall time of a place as the instant it names

Declare it on a field or a query parameter as `Annotated[datetime, LocalTimeIn(zone)]`, and an
optional one as that type `| None`. The field's own `datetime` reads the value first, with the
field's settings: in strict mode, text from Python is refused as a plain strict timestamp
refuses it, and JSON text is read. Then the type reads:

- a value without a UTC offset as a local time in the zone: `2026-11-06T10:00` in
  `Europe/Amsterdam` is `2026-11-06T09:00:00Z`, and `2026-07-01T10:00` is `08:00` UTC;
- a bare date as its midnight in the zone, so on a day whose midnight the clocks skip or repeat
  there (in 2026, 8 March and 1 November in `America/Havana`) it is refused like any such time;
- a value with an offset, and a Unix time, as the instant it names;
- a `datetime` object the same way as text, since what the type means does not depend on who
  built the value.

The value arrives aware and in UTC, so a declared filter takes it and `UtcDateTime` stores it
as it is. A time that, read as UTC, falls before year 1 or after 9999 is a 422 of type
`timestamp_out_of_range`, not an overflow.

The zone is the app's, declared on the field, as a filter declares the zone whose day it is
(ADR 0206, decision 3); the caller does not send it. A client that knows the person's own zone
sends the offset, as `DateTimeInput` does. A declaration is checked when it is made:

- a zone the server does not know raises a `ValueError` that names an IANA zone as the fix;
- a zone that names no place raises a `ValueError` that names `NaiveMeansUtc`. That is UTC under
  any of its names (`UTC`, `Etc/Zulu`, `GMT`), a fixed offset (`Etc/GMT-1`, `EST`), and the
  host's own setting (`localtime`, `posixrules`). A zone counts as a place when its offset has
  ever changed: every place began on its own mean solar time and has moved since, while UTC and
  a fixed offset never have. Reading a time in UTC is `NaiveMeansUtc`'s, which the rule counts,
  so the type does not offer it unmarked. A place that keeps UTC today, such as
  `Atlantic/Reykjavik`, is still a place;
- `LocalTimeIn` on anything but a plain `datetime`, or after other metadata, raises a
  `TypeError` that says where it goes: directly after `datetime`.

### 2. A wall time the clocks skip or repeat is refused

The type reads the wall time both ways it can be read, before and after a change of the
clocks, and counts each instant that reads back as that wall time. One is the instant. None
means the clocks skip it there, and two that they repeat it. Both are a 422 at the value's
place:

- `local_time_skipped`: *2026-03-29T02:30:00 does not happen in Europe/Amsterdam, where the
  clocks skip it; send a time that happens there, or one with its UTC offset*
- `local_time_repeated`: *2026-10-25T02:30:00 happens twice in Europe/Amsterdam, where the
  clocks repeat it; send it with its UTC offset, 2026-10-25T02:30:00+02:00 or
  2026-10-25T02:30:00+01:00*

Counting what reads back, rather than comparing the two offsets, matters where the zone data is
not consistent with itself. In the `tzdata` package's data (2026f) for `America/Nuuk`, 23:30 on
28 October 2023 reads once with a rule that had not started yet (-01), which does not read
back, and once as -02, which does; the wall time happens once and is taken.

`DateTimeInput` chooses instead: it moves a skipped time forward past the gap and takes the
earlier of a repeated one. It can, because a person sees the time it shows and can change it.
The server reads text from any sender and cannot ask, and a guess here is the error ADR 0206
refuses. A sender that meant one of the two sends its offset.

### 3. It is no escape, and its contract is a `datetime`'s

The type's reader runs behind the timestamp, as `NaiveMeansUtc`'s does. A `BaseSchema` leaves
that node as the type built it, and knows it by the reader's own function, bound to an instance
of the type itself, as it knows the escape's node by its function. Any other function, bound to
anything, is not trusted, and the timestamp in front of it is judged as before. The type cannot
be subclassed, and an instance cannot be changed once declared, so the reader the walk trusts is
the one the type defines. The walk takes that reader when the framework loads, before any app
code runs, so a function put on the class afterwards is not it either. The fields beside it are
judged as before, and the rule does not count it.

Its JSON schema is a `datetime`'s, `format: date-time`, as `NaiveMeansUtc`'s is. The contract
describes what a client should send, an instant with its offset, and the type takes that too. A
field that adopts it publishes what a plain `datetime` field publishes.

### 4. An app's own early validator on a timestamp is the escape

The rule counts each of these:

- a `BeforeValidator`, `WrapValidator` or `PlainValidator`, or a name bound to one, in an
  `Annotated` type that reads a timestamp, where that type is spelled. That includes
  `datetime`, `AwareDatetime` and Pydantic's other datetime types, in a union, a list or a
  quoted annotation;
- each use of a name bound to such a type, as each use of a name bound to `NaiveMeansUtc`
  counts, so one marker never covers more than one field;
- a `field_validator` in `before`, `wrap` or `plain` mode, or Pydantic 1's `validator` with
  `pre=True`, written as a decorator or a call in the body of a class or of a base the same file
  defines, on a field that class or one of those bases declares as a timestamp. The field may be
  named, matched by `"*"`, or given as a field name or a mode the file computes, which the rule
  cannot read and so counts. A shared base whose `"*"` validator reads text is counted when a
  class below it has a timestamp.

Every name is followed through the file's imports and assignments: an alias of `Annotated`, of
a validator or of `field_validator`, and a type alias over a timestamp, `NewType` and
`TypeAliasType` included.

It does not count:

- an after validator, which sees the instant the type made;
- a validator on a field that is no timestamp; a `date` is a day;
- a validator of the whole model, which sees the body rather than a field. ADR 0206 recorded
  that counting it would mostly be noise.

A use stands when its line, or the line above, carries
`# arch-allow-request-timestamps-carry-their-offset: <reason>`, which the app's
`escape-hatch-budget.json` counts. The corpus records four residuals:

- a field or a validator a base in another module declares;
- a timestamp alias imported from another module;
- a model validator;
- a validator a schema only gets at run time.

### 5. This half is build-time, by decision

The runtime half of the rule is still ADR 0206's refusal. An app's own early validator runs in
front of it and hands it an instant, so at run time its reading of a time without an offset
looks like the client's. The schema walk could see a `before` or `wrap` validator around a
timestamp, but it cannot tell one a person marked from one they did not, since the marker is a
comment in the source. So this half is held at build time, as the escape's governance is, and
the catalog entry's rationale says so. The runtime applicability stays `required`, for the
refusal.

## What does not change

- **An app with neither** an early validator on a timestamp nor the new type.
- **`NaiveMeansUtc`**, the escape for a sender known to send UTC, and its marker.
- **The contract.** Decision 3 publishes what a `datetime` publishes.
- **`DateTimeInput` and the frontend rule.** A form still sends an instant. A field that sends
  the wall time of a place keeps its `datetime-local` control with that rule's marker, and the
  API reads it with `LocalTimeIn`.

## Consequences

- An app with an early validator on a timestamp field fails the gate. It takes `LocalTimeIn`
  where the validator read the wall time of a known place, an after validator where it only
  checked the instant, or the marker and a budget entry where it must keep reading the text.
- Three new error types reach a client: `local_time_skipped`, `local_time_repeated` and
  `timestamp_out_of_range`.
- A schema that uses `LocalTimeIn` for a response as well reads a naive value the server built
  as that place's wall time too. A row read back through `UtcDateTime` is aware already and
  passes as the instant it is.
- ADR 0206's other two 0.39.0 items remain: the startup check of a request body that is not a
  `BaseSchema`, and of a plain timestamp route parameter.

## What the review changed

An independent review of the first build found:

- **`LocalTimeIn("UTC")` was `NaiveMeansUtc` without the marker,** and so were `GMT`, `Zulu` and
  the other names of UTC, and `localtime`, which reads in whatever zone the host is set to. A
  zone that names no place is now refused when declared (decision 1).
- **A subclass of the type was a quiet escape.** The walk trusted any instance's method, so a
  subclass whose reader passed the text through was left unjudged, and a declared instance could
  be changed afterwards. The type now refuses a subclass and any change, and the walk trusts
  only the type's own function, as the type defined it when the framework loaded (decision 3).
- **A time near year 1 or 9999 was a 500,** an overflow, where a plain timestamp gives a 422. It
  is now `timestamp_out_of_range`.
- **The reader ignored the field's own settings.** It parsed with a lax reader of its own, so a
  strict field took text it should refuse. The field's own `datetime` now reads first.
- **A wall time that happens once could be refused as skipped** where the zone data disagrees
  with itself (decision 2).
- **The rule missed** a validator a base declares for a subclass's field, a `field_validator`
  written as a call, and names bound by assignment rather than import. It now follows all three
  (decision 4), and records what it still leaves alone.
- **A type alias carrying an early validator was counted once,** however many fields used it,
  where `NaiveMeansUtc`'s aliases count at each use. It now counts at each use.
- **The rule recursed** through a long chain of concatenations and could exhaust its stack on a
  file the parser takes. Its walks now keep their own lists.
- **The remedy in `BaseSchema`'s refusal of a taken hook** named the type as if it were a type,
  and now spells the declaration.
