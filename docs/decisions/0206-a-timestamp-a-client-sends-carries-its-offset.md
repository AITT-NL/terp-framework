# 0206 — A timestamp a client sends carries its UTC offset

- **Status:** Accepted on 2026-11-06. The owner decided
  [ADR 0205](0205-a-timestamp-column-stores-an-instant-as-utc.md)'s open question A on the
  recommendation this records: refuse a timestamp without an offset where it enters, in a
  record of its own. Built in 0.38.0.
- **Date:** 2026-11-06.
- **Relates:** [ADR 0205](0205-a-timestamp-column-stores-an-instant-as-utc.md) (its open
  question A, and the `UtcDateTime` that reads a naive value as UTC),
  [ADR 0194](0194-an-apps-api-contract-is-a-committed-file.md) (the committed contract, which
  does not change), [ADR 0059](0059-strict-frontend-boundary-and-escape-hatch-budget.md)
  (no modes: the one way around is a budgeted escape), and the
  `request_timestamps_carry_their_offset` rule.

## Decision

A timestamp a client sends must carry its UTC offset. A request body built on `BaseSchema`
refuses text that reads as a date and time without one, as a 422 at the field. A declared
filter refuses a bound without one, as a 400 that names the filter. Both say what to send. The
published contract does not change, because it already requires the offset. The one way around
is `NaiveMeansUtc`, which reads a value without an offset as UTC. The
`request_timestamps_carry_their_offset` rule refuses each use of it unless the line carries the
rule's marker, which the app's escape-hatch budget counts.

## Context

ADR 0205 made a timestamp column store an instant as UTC on every dialect. Given a naive value,
it reads it as UTC. That is right for a value the server built in UTC and silently wrong for one
a client sent in its own zone. A client in Amsterdam that sends `2026-11-06T10:00:00`, meaning
ten in the morning there, is stored at 10:00 UTC, an hour late, and nothing reports it. ADR 0205
left this as its open question A, because refusing such a value looked like a change to every
app's request contract. Two facts settled it:

- **The contract already rules the value out.** A `datetime` field is published as
  `{"type": "string", "format": "date-time"}`, and `date-time` is RFC 3339's production, whose
  offset is required. Pydantic's plain `datetime` accepts more than the contract allows, and the
  column guesses UTC for the rest.
- **Refusing it changes no contract text.** Pydantic publishes an aware-only field exactly as a
  plain one, so ADR 0194's committed `openapi.json` stays byte-identical and its check sees
  nothing. A client generated from the contract already sends the offset. The client that breaks
  is a hand-written one sending a bare local time, which is the one stored wrongly today.

## Decisions

### 1. A request body refuses a timestamp without an offset, at the field

Before any field is validated, `BaseSchema` judges every field typed `datetime`,
`datetime | None`, or a list of either. Text that reads as a date and time with no offset, such
as `2026-11-06T10:00:00` or a bare date `2026-11-06`, is refused with the error type
`timestamp_offset_required` and this message:

> A date and time needs its UTC offset, for example 2026-11-06T10:00:00Z or
> 2026-11-06T11:00:00+01:00

The error sits at the field: under its parent for a nested body, at its index for a list, and
under the alias the client sent. FastAPI renders it as its usual 422, with `loc`
`["body", "<field>"]`, so a form maps it to its input. Every such field in a body is named at
once. The refusal runs before the fields are validated, so a body's other errors appear once its
timestamps carry their offsets.

### 2. Only a client's text is judged

An object that reaches a schema was built by the server: a row read back, or a value computed in
code. A number is a Unix time, which is UTC. Neither is judged. So a response model built from
rows validates exactly as before, and so does a schema constructed in code from a `datetime`. A
field typed to accept text as well (`datetime | str`) is not read as a timestamp.

### 3. A declared filter refuses a bound without an offset

A route forwards its query parameters to `filters=`, and by then FastAPI has parsed a timestamp
parameter into a `datetime`, which is naive if the client sent no offset. `FilterField` refuses
it with a `ValidationFailedError`, a 400: *Filter 'taken_after' needs a date and time with its
UTC offset, for example 2026-11-06T10:00:00Z.* This holds for every comparison, for each item of
an `in` list, and for a statistic's filters, which resolve the same way.

### 4. The contract does not change

Decision 1 refuses at validation, not in the schema, so a field's schema text is unchanged. The
committed contract, every client generated from it and the `api-contract` check are untouched.

### 5. The one way around is `NaiveMeansUtc`, and it is an escape

Some senders do send UTC without saying so, such as an export from another system or a device
clock. A field or a query parameter typed `NaiveMeansUtc` reads a value without an offset as UTC.
The value arrives aware, so a declared filter takes it too.

The `request_timestamps_carry_their_offset` rule refuses every use of it: by name, under an
alias, through the `terp.core` module, or in a quoted annotation. The use stands only when its
line carries `# arch-allow-request-timestamps-carry-their-offset: <reason>`, which the app's
`escape-hatch-budget.json` counts (ADR 0059). So taking it is a person's decision, made in
review, and never a default. A class of the same name from anywhere else is not the escape,
because the boundary does not step aside for it.

### 6. Two layers

The runtime refusals in decisions 1 and 3 hold the invariant, and the rule governs the one way
around them. The rule's catalog entry classifies its runtime half as `required` and cites both
controls.

## What does not change

- **What is stored.** `UtcDateTime` still reads a naive value the server hands it as UTC
  (ADR 0205), and `no_naive_datetime` still refuses the naive constructors.
- **Everything that is not a client's timestamp text:** a `date` field, a response, a cursor
  (the framework writes it), and a schema built in code.
- **The contract file**, and every client generated from it.

## Open

- **A request model that is not a `BaseSchema`.** A plain Pydantic model used as a request body
  is not held to decision 1. The convention already makes every DTO a `BaseSchema`, but no rule
  refuses the plain model yet. A rule for it is a later revision.
- **A timestamp route parameter that is not a declared filter.** FastAPI parses it, and nothing
  judges it unless it reaches a filter. Until a check covers it, take it through a declared
  filter, or type it with Pydantic's `AwareDatetime`, whose 422 does not name the fix.

## Consequences

- **A client that sends a bare local time breaks.** It gets a 422 that says what to send, instead
  of being stored off by its offset. That is a breaking change for that client, and the
  CHANGELOG's upgrade notes say so.
- **An app with a sender that truly sends UTC without an offset** declares the escape on that one
  field, with the reason, in the same change.
