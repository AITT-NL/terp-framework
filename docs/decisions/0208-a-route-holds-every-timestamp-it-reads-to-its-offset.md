# 0208 — A route holds every timestamp it reads to its offset, checked when the app starts

- **Status:** Accepted on 2026-11-07. The owner decided it on 2026-11-06, as two of the open
  questions of [ADR 0206](0206-a-timestamp-a-client-sends-carries-its-offset.md): a model that
  is not a `BaseSchema`, as a request body or nested in one, and a timestamp route parameter
  that is not a declared filter. It follows the recommendation that record keeps under *Open*.
  Built in 0.39.0 (unreleased). An independent review of the first build changed it (see *What
  the review changed*).
- **Date:** 2026-11-07.
- **Relates:** [ADR 0206](0206-a-timestamp-a-client-sends-carries-its-offset.md) (the refusal,
  the escape and the declared filter's refusal),
  [ADR 0207](0207-a-local-time-in-a-named-zone-is-a-type-and-an-early-validator-is-the-escape.md)
  (`LocalTimeIn`, and an app's own early validator as the escape), and
  [ADR 0084](0084-runtime-applicability-classification.md) (the runtime half a rule
  cites).

## Decision

`Instant`, from `terp.core`, is a `datetime` with ADR 0206's refusal in front of it:
`since: Instant | None = None`. Text without a UTC offset is a 422, as it is in a `BaseSchema`.

`create_app` walks, once every router is mounted, the schema each route reads each of its
parameters with. It refuses to start while one reads a timestamp that nothing holds to its
offset, and names every such timestamp and the fix.

## Context

ADR 0206 refuses timestamp text without an offset in every field a `BaseSchema` reads itself.
Two kinds of request value are read by nothing of the kind:

- **A route parameter.** FastAPI parses `since: datetime` itself, so `2026-11-06T10:00:00`
  arrives naive. A declared filter refuses a naive bound, but only a value that reaches one.
- **A class that reads its own fields:** a plain Pydantic model, a Pydantic dataclass, a root
  model or a table. Pydantic validates it with its own validator wherever it sits, as a body or
  nested in a `BaseSchema`. ADR 0206's fourth round found that judging one in front of that
  validator runs the class's validators twice, changes which member a union picks, and breaks
  the published JSON schema.

Neither can be judged where it is read without changing what it reads. Both can be seen before
the app serves anything.

## Decisions

### 1. `Instant` is the refusal as a type

`Instant` is `Annotated[datetime, …]`, with the refusal ADR 0206 puts in front of every
timestamp a `BaseSchema` reads. Text without an offset is a 422 of type
`timestamp_offset_required`, with that record's message, at the value's place. Text with an
offset, a `datetime` object and a Unix time are read as a plain `datetime` reads them, as they
are in a `BaseSchema`.

Declare it on a route parameter (path, query, header or cookie), on a field of a class that
is not a `BaseSchema`, and on the parameter of a declared filter. In a `BaseSchema` it is the
schema's own refusal, once, since the walk knows the node by its function. Its JSON schema is a
`datetime`'s, so a parameter that moves from `datetime` to `Instant` publishes what it did.

It is no escape: it refuses what the escape takes, so the rule does not count it. An app's own
early validator in front of it reads the text first, as one in front of a `datetime` does, and
the rule counts that one the same way (ADR 0207, decision 4).

### 2. The check walks what each route reads

Once every router is mounted (the app's modules, every capability and the framework's own),
`create_app` reads every HTTP and WebSocket route. For each parameter FastAPI reads for the
route, and for every dependency the route resolves, it walks the schema the parameter is read
with: its type and every piece of metadata on it. That covers a path, query, header or cookie
parameter, a body or form field, and a parameter model as a whole. The walk follows every
definition, list, mapping, tuple, union and class it reaches.

A timestamp is held when it stands behind one of these:

- the refusal, `Instant`'s or the one a `BaseSchema` puts in front of its own fields, known by
  its function;
- `LocalTimeIn`'s reader, known by the type's own function (ADR 0207, decision 3);
- `NaiveMeansUtc`'s validator, the escape the rule counts at build time;

or when it is an aware-only `datetime` (Pydantic's `AwareDatetime`), which refuses a value
without an offset itself. Anything else is not held: a plain `datetime`, a `NaiveDatetime`, a
`PastDatetime` or `FutureDatetime`, and a `datetime` behind an app's own validator.

A `BaseSchema` needs no exception. Its own fields are held already, and a class inside it that
reads its own fields is walked like any other.

A router `create_app` mounts takes no route once the app is composed, as the app itself takes
none. FastAPI serves an included router live, so a route added to one afterwards would be served
without this check, or any other `create_app` runs on every route it reads. Every registration
method of every router it mounted, at any depth, raises a `BootError` that names the method and
the remedy: declare every route before `create_app` runs. A method nobody named, or one called on
its class with the router passed in, still ends in a change to a list the app reads, so those
lists refuse a change themselves: every router's routes, FastAPI's frontend routes, the
lifecycle hooks and the middleware.

### 3. One refusal names every timestamp and the fix

`create_app` raises one `BootError` that names, for every timestamp not held:

- the route, by its methods and its path as mounted;
- the parameter, by where it is read (a path or query parameter, a header, a cookie or a body
  field) and the name a client sends it under;
- the class and field that declare the timestamp, when a class does.

For example: *POST /api/v1/bookings/ reads a timestamp in the body field 'booking', in
Window.opens_at*. The fix it names is `Instant`; `LocalTimeIn` for the wall time of a place;
`NaiveMeansUtc` for a sender known to send UTC without saying so; or turning the class into a
`BaseSchema`, or, where the class is not the app's to change, a `BaseSchema` of the app's own in
its place.

### 4. What the check leaves alone

- **A response model and a computed field.** They are written, never read from a request.
- **A `date`.** A day is not a timestamp.
- **A validator that replaces the type** (`PlainValidator`). It leaves no timestamp for the walk
  to see. It is an app's own early validator, which the rule counts at build time where the type
  under it is spelled as a timestamp, `Instant` included (ADR 0207, decision 5).
- **A validator's JSON schema input** (`json_schema_input_type`). Pydantic uses it only to
  publish the contract, so nothing is read through it.
- **A path convertor of the app's own.** Starlette converts a path segment before FastAPI
  validates it, so a convertor that builds a `datetime` hands `Instant` an object, which it does
  not judge. Such a convertor is the app's own parser, as an early validator is. Starlette's own
  convertors hand a timestamp parameter text.
- **A dependency put in place through `dependency_overrides`,** the principal provider
  `create_app` installs that way included. FastAPI reads its parameters only at request time,
  and a provider reads credentials, not timestamps. The `no_dependency_overrides` rule refuses
  the mechanism to an app's own code.

### 5. A declared filter's timestamp parameter is typed `Instant`

ADR 0206 sent a timestamp route parameter through a declared filter, whose refusal is a 400
that names the filter. That refusal stays for a bound the app's own code hands a filter. A
parameter that feeds one is now typed `Instant`, so a bound without an offset from a client is
a 422 at the parameter, before any filter sees it.

### 6. The check is the runtime half for what a `BaseSchema` does not read itself

The rule's catalog entry cites it beside the refusal and the filter's refusal. The build-time
half is unchanged: it governs the escape and an app's own early validator.

A plain timestamp parameter has no build-time half, by decision. The app does not start, which
every test of the app and every deploy shows. And the check reads what a scan of the source
cannot: a parameter a dependency declares, a type an alias names, and a class from another
module.

## What does not change

- **A `BaseSchema` body.** It is held as before, and the walk finds its timestamps held.
- **`NaiveMeansUtc`, its marker and `LocalTimeIn`.**
- **The contract.** `Instant` publishes a `datetime`'s schema.
- **What is stored.** `UtcDateTime` reads a value as it did (ADR 0205).

## Consequences

- An app does not start while a route reads a plain timestamp parameter, or a body that is or
  nests a class with its own validator holding one. The refusal names each one and its fix. A
  declared filter's timestamp parameter is the common case: type it `Instant`.
- Startup builds a validator for every parameter of every route once, as FastAPI already did.
- A route can no longer be added to a router `create_app` mounted, once it has run.
- The items ADR 0206 decided for 0.39.0 are built: this record, and ADR 0207.

## What the review changed

An independent review of the first build found:

- **`Instant` hid an app's own early validator from both halves.** The walk stops at its refusal,
  and the rule did not know its name, so `Annotated[Instant, BeforeValidator(f)]` and a `before`
  field validator on an `Instant` field read text unseen. The rule now reads `Instant` as a
  timestamp type (decision 1), and the corpus holds both forms.
- **A route added to a mounted router after `create_app` returned was served unchecked,** since
  FastAPI serves an included router live. Every router `create_app` mounts now refuses
  registration (decision 2).
- **The walk read a validator's JSON schema input,** and so refused a validator that only
  publishes `date-time` (decision 4).
- **A schema with no class behind it crashed the walk** with a `KeyError`. It is read by its
  fields now.
- **The remedy assumed the class was the app's to change.** It names a `BaseSchema` of the app's
  own in its place (decision 3).

A second review, of 0.39.0 before its release, found that the freeze refused registration
methods by name and so missed `host` and `frontend` (FastAPI's), a method called on its class
with the router passed in, and the route list itself. A route added any of those ways was served
without the module guard, on the app as on a mounted router. The lists now refuse a change
themselves (decision 2), and so do the lifecycle hooks and the middleware, which the same
spellings reached.
- **A path convertor of the app's own** is recorded as a limit (decision 4).
