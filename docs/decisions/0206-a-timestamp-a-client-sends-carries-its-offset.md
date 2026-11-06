# 0206 — A timestamp a client sends carries its UTC offset

- **Status:** Accepted on 2026-11-06. The owner decided
  [ADR 0205](0205-a-timestamp-column-stores-an-instant-as-utc.md)'s open question A on the
  recommendation this records: refuse a timestamp without an offset where it enters, in a
  record of its own. Built in 0.38.0. An independent review of the first build found the
  refusal judged by guessing at field shapes and keys, and a job's own payload refused. The
  refusal now sits at the timestamp type (see *What the review changed*).
- **Date:** 2026-11-06.
- **Relates:** [ADR 0205](0205-a-timestamp-column-stores-an-instant-as-utc.md) (its open
  question A, and the `UtcDateTime` that reads a naive value as UTC),
  [ADR 0194](0194-an-apps-api-contract-is-a-committed-file.md) (the committed contract, which
  does not change), [ADR 0059](0059-strict-frontend-boundary-and-escape-hatch-budget.md)
  (no modes: the one way around is a budgeted escape), and the
  `request_timestamps_carry_their_offset` rule.

## Decision

A timestamp read as text must carry its UTC offset. A `BaseSchema` refuses timestamp text
without one wherever Pydantic reads a timestamp for it, as a 422 at its place. A declared filter
refuses a bound without one, as a 400 that names the filter. Both say what to send. The
published contract does not change, because it already asks for the offset. The framework's one
way around is `NaiveMeansUtc`, which reads a value without an offset as UTC. The
`request_timestamps_carry_their_offset` rule refuses each use of it unless the line carries the
rule's marker, which the app's escape-hatch budget counts.

## Context

ADR 0205 made a timestamp column store an instant as UTC on every dialect. Given a naive value,
it reads it as UTC. That is right for a value the server built in UTC and silently wrong for one
a client sent in its own zone. A client in Amsterdam that sends `2026-11-06T10:00:00`, meaning
ten in the morning there, is stored at 10:00 UTC, an hour late, and nothing reports it. ADR 0205
left this as its open question A, because refusing such a value looked like a change to every
app's request contract. Two facts settled it:

- **The contract already asks for the offset.** A `datetime` field is published as
  `{"type": "string", "format": "date-time"}`, and `date-time` is RFC 3339's production, whose
  offset is required. Pydantic's plain `datetime` accepts more than the contract allows, and the
  column guesses UTC for the rest.
- **Refusing it changes no contract text.** The refusal runs at validation, not in the schema,
  so ADR 0194's committed `openapi.json` stays byte-identical and its check sees nothing. A
  client generated from the contract is typed with a string: it sends what the app gives it, so
  one that sends a bare local time gets the 422, and the 422 says what to send.

## Decisions

### 1. Timestamp text without an offset is refused, at the timestamp type

`BaseSchema`'s schema hook puts the refusal in front of every `datetime` in the schema Pydantic
builds for a subclass. So it runs wherever Pydantic validates a timestamp: a field, an item of
a list or a tuple, a value of a mapping, a member of a union, a `NewType` over one, a nested
model, and under whatever name Pydantic reads the value by, an alias, a choice of aliases or a
path. Text that reads as a date and time with no offset, such as `2026-11-06T10:00:00` or a bare
date `2026-11-06`, is refused with the error type `timestamp_offset_required` and this message:

> A date and time needs its UTC offset, for example 2026-11-06T10:00:00Z or
> 2026-11-06T11:00:00+01:00

FastAPI renders it as its usual 422, with `loc` `["body", "<field>"]` and deeper for an item or
a nested model, so a form maps it to its input. Every such value in a body is named in the same
error, beside the body's other errors.

A member of a union that is not a timestamp still takes what it takes: `datetime | str` keeps
the text, and `datetime | date` reads a bare date as a date. A field typed `NaiveDatetime` takes
no timestamp text at all, since the refusal stops the naive kind and the type stops the aware
kind. A subclass that replaces the schema hook is refused when it is defined.

### 2. Only text is judged, and the framework trusts the text it wrote itself

An object that reaches a schema was built by the server: a row read back, or a value computed
in code. A number is a Unix time, which is UTC. Neither is judged. So a response model built
from rows validates exactly as before, and so does a schema constructed in code from a
`datetime`.

The framework writes a job's payload as text when it is enqueued and reads it back in the
worker. A naive value the server built is written without an offset (ADR 0205 reads one as
UTC), so the worker's read passes a validation context the refusal trusts, and the handler gets
the value as it was built. That is the one round trip the framework makes through text.

Any other text a schema reads is judged as a client's: a realtime message a client sends, a
mapping the app's own code hands a schema, a payload passed to `enqueue` as a mapping, and a
row read by literal SQL on SQLite, whose driver returns timestamps as text.

### 3. A declared filter refuses a bound without an offset

A route forwards its query parameters to `filters=`, and by then FastAPI has parsed a timestamp
parameter into a `datetime`, which is naive if the client sent no offset. `FilterField` refuses
it with a `ValidationFailedError`, a 400: *Filter 'taken_after' needs a date and time with its
UTC offset, for example 2026-11-06T10:00:00Z.* This holds for every comparison, for each item of
an `in` list, and for a statistic's filters, which resolve the same way. It holds for a bound
the app's own code passes as well, since a filter cannot tell who built it.

### 4. The contract does not change

Decision 1 refuses at validation, not in the schema, so a field's schema text is unchanged. The
committed contract, every client generated from it and the `api-contract` check are untouched.

### 5. The framework's one way around is `NaiveMeansUtc`, and it is an escape

Some senders do send UTC without saying so, such as an export from another system or a device
clock. A field or a query parameter typed `NaiveMeansUtc` reads a value without an offset as UTC.
The value arrives aware, so a declared filter takes it too.

The `request_timestamps_carry_their_offset` rule fails closed by name. It refuses every
reference to `NaiveMeansUtc`: as a name, as an attribute, through `getattr` with that literal
name, in a quoted annotation, and under every name the file binds to it, at each use. A
re-export of it, and a class of that name the file defines, count as the escape too, and so
does an import of `terp.core.timestamps`, the boundary's own machinery. A use stands only when
its line carries `# arch-allow-request-timestamps-carry-their-offset: <reason>`, which the
app's `escape-hatch-budget.json` counts (ADR 0059). So taking it is a person's decision, made in
review, and never a default. The rule holds every root that ships Python, a worker as much as
the app, because the refusal runs wherever a schema reads text.

### 6. Two layers

The runtime refusals in decisions 1 and 3 hold the invariant, and the rule governs the
framework's way around them. The rule's catalog entry classifies its runtime half as
`required` and cites both controls.

## What does not change

- **What is stored.** `UtcDateTime` still reads a naive value the server hands it as UTC
  (ADR 0205), and `no_naive_datetime` still refuses the naive constructors.
- **Everything that is not timestamp text:** a `date` field, a response built from rows, a
  cursor (the framework writes it), a job payload built from a model, and a schema built in code
  from objects.
- **The contract file**, and every client generated from it.

## Open

- **A request model that is not a `BaseSchema`.** A plain Pydantic model used as a request body
  is not held to decision 1. The convention already makes every DTO a `BaseSchema`, but no rule
  refuses the plain model yet. A rule for it is a later revision.
- **A timestamp route parameter that is not a declared filter.** FastAPI parses it, and nothing
  judges it unless it reaches a filter. Until a check covers it, take it through a declared
  filter, or type it with Pydantic's `AwareDatetime`, whose 422 does not name the fix.
- **A validator of the app's own that runs first.** A model or field validator in `before` mode
  sees the text before the timestamp type does, so it can read a naive value with a zone of its
  choosing. That is also how a "wall time plus a named zone" input is read. It is the app's own
  code, which a reviewer reads, and the rule does not count it. Whether the rule should govern
  it is the owner's question.
- **A `date` bound on a timestamp column.** A declared filter still takes a bare date as UTC
  midnight, the reading `UtcDateTime` gives one. For a caller in another zone, that day starts
  off by the zone's offset, the same outcome this ADR refuses for a naive date and time. Whether
  to refuse a date bound on a timestamp column, or to name its zone, is the owner's question.
- **The frontend half.** `@terpjs/react-core` has no primitive that turns a picked local date
  and time into an instant. A form that sends the value of a `datetime-local` input sends a time
  without an offset, which this ADR now refuses. Whether the frontend gets that primitive, or a
  lint rule for the raw value, is the owner's question.
- **An alias across modules.** A name bound to `NaiveMeansUtc` in one module and imported into
  another under a different name counts once, where it is bound. The corpus records it as a
  residual.

## What the review changed

The first build was reviewed independently before its pull request. Each finding is fixed in
the build:

- **The refusal guessed.** It was a model validator that judged a body's raw keys against the
  field shapes it recognised. It missed a timestamp under `Sequence`, `dict`, a tuple, a nested
  list, `NewType`, `FutureDatetime` and a union with another type, and it judged the name
  rather than the alias Pydantic reads. It now sits at the timestamp type, decision 1.
- **A job's payload was refused in the worker.** The refusal read every mapping as a client's
  body, so a naive value a job was enqueued with came back as text and failed before its
  handler. The worker's read is now trusted, decision 2.
- **The escape could be taken unseen.** The rule followed the escape through imports, so a
  re-export, a name reached through the `terp` package and an alias bound once and used twice
  were missed. It now fails closed by name, decision 5. A subclass could also replace the
  refusal by overriding it; that is refused when the class is defined.
- **Prose that claimed more than the code.** It said a generated client already sends the
  offset, that the nested errors came in the same response, and that `NaiveMeansUtc` was the
  only way around. Each is corrected above.

## Consequences

- **A client that sends a bare local time breaks.** It gets a 422 that says what to send, instead
  of being stored off by its offset. That is a breaking change for that client, and the
  CHANGELOG's upgrade notes say so, with the other text the refusal now judges.
- **An app with a sender that truly sends UTC without an offset** declares the escape on that one
  field, with the reason, in the same change.
