# 0206 — A timestamp a client sends carries its UTC offset

- **Status:** Accepted on 2026-11-06. The owner decided
  [ADR 0205](0205-a-timestamp-column-stores-an-instant-as-utc.md)'s open question A on the
  recommendation this records: refuse a timestamp without an offset where it enters, in a
  record of its own. Built in 0.38.0. Four rounds of independent review changed the build: the
  refusal now sits at the timestamp type, follows every definition a schema reads itself, leaves
  a class with its own validator to that validator, and trusts only what an app reaches by
  importing the boundary's own module, which the rule refuses (see *What the review changed*).
  Later on 2026-11-06 the owner decided its open questions on the recommendations recorded
  here. A calendar day on a timestamp filter names its zone or is refused, and a form sends an
  instant (decisions 3 and 7, both in 0.38.0). An app's own validator that reads timestamp text
  first, a model that is not a `BaseSchema` and a plain timestamp route parameter are each
  decided for 0.39.0 (see *Open*).
- **Date:** 2026-11-06.
- **Relates:** [ADR 0205](0205-a-timestamp-column-stores-an-instant-as-utc.md) (its open
  question A, and the `UtcDateTime` that reads a naive value as UTC),
  [ADR 0194](0194-an-apps-api-contract-is-a-committed-file.md) (the committed contract, which
  does not change), [ADR 0059](0059-strict-frontend-boundary-and-escape-hatch-budget.md)
  (no modes: the one way around is a budgeted escape), and the
  `request_timestamps_carry_their_offset` rule.

## Decision

A timestamp read as text must carry its UTC offset. A `BaseSchema` refuses timestamp text
without one wherever it reads a timestamp itself, as a 422 at its place. A declared filter
refuses a bound without one, as a 400 that names the filter, and a calendar day unless the
filter declares the zone whose day it is. Both say what to send. A form sends an instant:
`DateTimeInput` sends what is picked with its zone's offset, and a raw `datetime-local` control
is lint-refused. The published contract does not change, because it already asks for the
offset. The framework's one way around is `NaiveMeansUtc`, which reads a value without an offset
as UTC. The `request_timestamps_carry_their_offset` rule refuses each use of it unless the line
carries the rule's marker, which the app's escape-hatch budget counts.

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

`BaseSchema`'s schema hook puts the refusal in front of every `datetime` the schema Pydantic
builds for a subclass reads itself, following every definition that schema refers to: a field,
an item of a list or a tuple, a value of a mapping, a member of a union, a `NewType` or a type
alias over one, a stdlib dataclass and a `TypedDict`, under whatever name Pydantic reads the
value by, an alias, a choice of aliases or a path. A nested `BaseSchema`, a recursive one and
schemas that refer to each other each hold their own the same way. Text that
reads as a date and time with no offset, such as `2026-11-06T10:00:00` or a bare date
`2026-11-06`, is refused with the error type `timestamp_offset_required` and this message:

> A date and time needs its UTC offset, for example 2026-11-06T10:00:00Z or
> 2026-11-06T11:00:00+01:00

FastAPI renders it as its usual 422, with `loc` `["body", "<field>"]` and deeper for an item or
a nested model, so a form maps it to its input. A member of a union is named as Pydantic names
it (`list[datetime]`, `dict[constrained-str,datetime]` under `BaseSchema`'s stripped strings),
except where it refers back to the schema it is in, which Pydantic writes `...` and the refusal
names by its name. Every such value in a body is named in the same error, beside the body's
other errors.

A class that brings its own Pydantic validator reads its own fields: a plain `BaseModel`, a
Pydantic dataclass, a root model, a table, or a model the framework builds, such as the one
`group_model` returns. Pydantic validates such a class with that validator whatever schema
surrounds it, so a schema cannot hold its timestamps, and the refusal leaves it exactly as it
was: its validators run once, a union picks among such classes as it always did, and its JSON
schema is its own. That is the same line the convention draws for a request model that is not a
`BaseSchema` (see *Open*): derive the class from `BaseSchema` to hold its timestamps. A nested
`BaseSchema` holds its own, since SQLModel validates it with its own validator too.

A member of a union that is not a timestamp still takes what it takes: `datetime | str` keeps
the text, and `datetime | date` reads a bare date, and a naive time of midnight, as a date. A
field typed `NaiveDatetime` takes no timestamp text at all, since the refusal stops the naive
kind and the type stops the aware kind. `BaseSchema`'s metaclass refuses, when a class is
defined, any subclass that takes the schema hook or the subclass hook,
`__get_pydantic_core_schema__` or `__pydantic_init_subclass__`, from anywhere but `BaseSchema`:
by defining it, at any depth, or from a base listed ahead of `BaseSchema`. A class that took
either would decide for itself and every class below it whether the refusal runs.

### 2. Only text is judged, and the framework trusts the text it wrote itself

An object that reaches a schema was built by the server: a row read back, or a value computed
in code. A number is a Unix time, which is UTC. Neither is judged. So a response model built
from rows validates exactly as before, and so does a schema constructed in code from a
`datetime`.

The framework writes a job's payload as text when it is enqueued and reads it back in the
worker. A naive value the server built is written without an offset (ADR 0205 reads one as
UTC), so the worker reads it while a context variable says the text is its own, which the
refusal trusts, and the handler gets the value as it was built. A variable, not a validation
context, because SQLModel validates a nested schema afresh, with no context, and the variable
reaches every schema the read does. Setting it means importing `terp.core.timestamps`, which the
rule refuses to an app (decision 5).
That is the one read of an app's own schema the framework trusts. Mail delivery also reads back
the message it sealed; that schema holds no timestamp, so nothing in it is judged, and a
timestamp added to it would be refused until its read is trusted too.

Any other text a schema reads is judged as a client's: a realtime message a client sends, a
mapping the app's own code hands a schema, a payload passed to `enqueue` as a mapping, and a
row read by literal SQL on SQLite, whose driver returns timestamps as text.

### 3. A declared filter refuses a bound without an offset

A route forwards its query parameters to `filters=`, and by then FastAPI has parsed a timestamp
parameter into a `datetime`, which is naive if the client sent no offset. `FilterField` refuses
it with a `ValidationFailedError`, a 400: *Filter 'taken_after' needs a date and time with its
UTC offset, for example 2026-11-06T10:00:00Z.* This holds for every comparison, for each item of
an `in` list, and for a statistic's filters, which resolve the same way. It holds for a bound
the app's own code passes as well, since a filter cannot tell who built it. A bound given as
text, which only the app's own code can give, is read as a date and time on a timestamp column
first, as a request's would be: text without an offset, and text that is none, are the same
400, and text with one becomes the instant it names.

A calendar day names no instant either, until it names the zone whose day it is. A filter on a
timestamp column used to read a bare date as UTC midnight, so for a caller in another zone the
day started off by the zone's offset: the error this ADR refuses, only on reads. A day on a
timestamp column is now the same 400, unless the filter declares its zone:
`FilterField("taken_on", Reading.taken_at, zone="Europe/Amsterdam")`. With one, a day is
compared as the whole of it in that zone, from its midnight to the next. `eq` is that day,
`gte` from its start, `lte` through its end, `gt` after it, `lt` before it, `ne` outside it, and
`in` any of the days. A day the clocks change on keeps its length, 23 or 25 hours. A zone is
declared on the filter, not sent by the caller, so a report's days are the business's own. A
filter declared wrongly is refused when it is declared: an op outside the fixed set, a zone the
server does not know, or a zone on a column that holds no timestamps.

### 4. The contract does not change

Decision 1 refuses at validation, not in the schema, so a field's schema text is unchanged. The
committed contract, every client generated from it and the `api-contract` check are untouched.

### 5. The framework's one way around is `NaiveMeansUtc`, and it is an escape

Some senders do send UTC without saying so, such as an export from another system or a device
clock. A field or a query parameter typed `NaiveMeansUtc` reads a value without an offset as UTC.
The value arrives aware, so a declared filter takes it too.

The `request_timestamps_carry_their_offset` rule fails closed by name. It refuses every
reference to `NaiveMeansUtc`: as a name, as an attribute, through `getattr` with that literal
name, and in a string Pydantic evaluates as a type, such as a quoted annotation, a forward
reference in `Optional["NaiveMeansUtc"]` or a field handed to `create_model`. It refuses every
name the file binds to it, at each use where that binding is the one in scope, and a class
attribute bound to it at each use of that attribute's name, through the class, a subclass or an
instance. A re-export of it, and a class of that name the file defines, count as the escape too,
and so does reaching `terp.core.timestamps`, the boundary's own module: an import of it, an
attribute or a literal `getattr` of `timestamps` on a name that means `terp.core` where it is
read, and the module's dotted name written as a literal. A use stands only when its line
carries `# arch-allow-request-timestamps-carry-their-offset: <reason>`, which the app's
`escape-hatch-budget.json` counts (ADR 0059). So taking it is a person's decision, made in
review, and never a default. The rule holds every root that ships Python, a worker as much as
the app, because the refusal runs wherever a schema reads text. It spares only the boundary's
own implementation: `terp.core`, which defines the boundary and its escape, and `terp.arch`,
which defines the rule and names both as the data it matches.

### 6. Two layers

The runtime refusals in decisions 1 and 3 hold the invariant, and the rule governs the
framework's way around them. The rule's catalog entry classifies its runtime half as
`required` and cites both controls.

### 7. A form sends an instant

A browser's `datetime-local` control hands the page a wall time with no offset, which decision
1 refuses. So `@terpjs/react-core` ships `DateTimeInput`. It shows an RFC 3339 instant as wall
time in a zone, the browser's own or one it is given (`zone="Europe/Amsterdam"`), and sends
what is picked as an RFC 3339 instant with that zone's offset. Its value is the API's own
string, so a form's state holds what the generated client sends. A wall time the clocks skip
moves forward past the gap, and one they repeat is the earlier of the two, the choice
JavaScript's dates and Temporal make. A value without an offset shows as empty rather than
guessed at.

The new rule `frontend/timestamp-inputs-carry-their-offset` refuses a JSX `type` of
`datetime-local` on any element, in any letter case, and names `DateTimeInput`. Its runtime half
is decision 1's refusal, which a wall time sent anyway meets at the server. `Input` itself does
not refuse the type at render, because then the rule's marker could not keep a field that truly
holds a wall time with a named zone, read by the API as text.

## What does not change

- **What is stored.** `UtcDateTime` still reads a naive value the server hands it as UTC
  (ADR 0205), and `no_naive_datetime` still refuses the naive constructors.
- **Everything that is not timestamp text:** a `date` field, a response built from rows, a
  cursor (the framework writes it), a job payload built from a model, and a schema built in code
  from objects.
- **A class with its own validator** nested in a schema: a plain model, a Pydantic dataclass, a
  root model, a table. It validates exactly as it did (decision 1).
- **The contract file**, and every client generated from it. Each schema's JSON schema is the
  one it publishes without the hook, its definitions' names included, which the suite holds
  against an SQLModel twin with `BaseSchema`'s config.

## Open

- **A model that is not a `BaseSchema`, as a request body or nested in one.** A plain Pydantic
  model, a Pydantic dataclass, a root model or a table reads its own fields, so it is not held to
  decision 1, whether it is the body or a field of one. The third round tried judging a nested
  one in front of its own validator, and the fourth found that it runs that class's validators
  twice, changes which member a union picks, and breaks the published JSON schema (see *What the
  review changed*). Decided on 2026-11-06, for 0.39.0: `create_app` checks every route when the
  app starts. It refuses a request body that is, or nests, such a class holding a timestamp the
  escape does not mark, naming the route and the fix. Response models are left alone.
  Built in 0.39.0 as
  [ADR 0208](0208-a-route-holds-every-timestamp-it-reads-to-its-offset.md).
- **A timestamp route parameter that is not a declared filter.** FastAPI parses it, and nothing
  judges it unless it reaches a filter. Decided on 2026-11-06, for 0.39.0: the same startup
  check refuses a plain `datetime` query or path parameter, and the framework ships a parameter
  type that refuses one without an offset. Built in 0.39.0 as
  [ADR 0208](0208-a-route-holds-every-timestamp-it-reads-to-its-offset.md): the check, and
  `Instant`, which a declared filter's timestamp parameter now takes.
- **A validator of the app's own that runs first.** A model validator in `before` or `wrap`
  mode, and a field validator in `before`, `wrap` or `plain` mode (`BeforeValidator`,
  `WrapValidator`, `PlainValidator`, `@field_validator`), sees the text before the timestamp
  type does, so it can read a naive value with a zone of its choosing. That is also how a "wall
  time plus a named zone" input is read. Moving the refusal to the timestamp type widened this:
  the first build's refusal ran before a field validator, and refused the naive text a
  `BeforeValidator` would have read. Decided on 2026-11-06, for 0.39.0: the framework ships a
  type for a local time in a named zone, which arrives as an instant and refuses a time the
  clocks skip or repeat. The rule then counts a `before`, `wrap` or `plain` validator on a
  timestamp field as the escape, with its marker and budget. A model-level validator sees the
  whole body, so flagging it would mostly be noise; it stays out, and stays recorded here.
  Built in 0.39.0 as
  [ADR 0207](0207-a-local-time-in-a-named-zone-is-a-type-and-an-early-validator-is-the-escape.md):
  `LocalTimeIn`, and the rule's count of such a validator.
- **What the rule sees only where the escape is named.** A name bound to `NaiveMeansUtc` in one
  module and imported into another under a different name, or bound by a `for` loop, a `with`
  statement or an assignment expression, counts where the escape is named, not at each use. The
  escape's own validator taken out of a schema that declares the escape and declared on another
  field by hand is the escape unnamed, and `vars(terp.core)` reaches the boundary's module
  unnamed. The corpus records each as a residual.

## What the review changed

The build was reviewed independently four times before its pull request. Each finding is fixed
in the build, except those recorded as open above. The first round:

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

The second round, of the rework:

- **A definition was never judged.** The hook saw a nested plain model, a dataclass, a
  `TypedDict` or a type alias as a reference to a definition, and could not see into it. It now
  follows each reference into a held copy of the definition. A nested model whose own complete
  validator Pydantic reuses was refused when the schema was defined; the third round replaced
  that refusal with judging first.
- **A field named like a schema setting was never judged.** The walk skipped keys such as
  `default` and `expected` at every level, including in a model's mapping of field names. It
  now reads a mapping of names by every key.
- **The trust and the escape's mark could be forged.** Both were strings an app could write
  into a context or a schema's metadata. They became an object and the escape's own validator,
  each compared by identity; the fourth round moved the trust to a context variable. The rule also refuses
  `terp.core.timestamps` however it is reached: `from terp.core import timestamps`, or an
  attribute of the `terp.core` package.
- **A class between could swallow the check.** A subclass that defined the subclass hook
  without passing it on spared every class below it. The check moved to `BaseSchema`'s
  metaclass, which runs for every class, decision 1.
- **The column rule refused declarations it should take.** `Annotated[datetime,
  Field(sa_type=UtcDateTime())]`, a column given a name in a variable, and `Column` imported
  under another name. Each is read now.
- **Smaller ones.** A union member's location carried the refusal's function name; it now
  carries the member's own name. The rule now follows a function's own local of the same name
  as that local, and a class attribute bound to the escape at each use. A machinery import is
  now told to recognise a refusal by its error type.

The third round, of the second rework, and what fixing it turned up:

- **A field named `type` broke the schema.** The walk read a model's mapping of field names as a
  schema node when a field was called `type`, and the class could not be defined. A mapping is
  now told from a node by whether its `type` is a kind.
- **The nested-model refusal refused what an app cannot change.** A schema that nested a model
  the framework builds, a table or a third party's model could not be defined, and the remedy it
  named could not be applied to them. Such a class was then judged in front of its own
  validator, which the fourth round undid.
- **Schemas that refer to each other could not be defined.** The hook asked Pydantic for a
  definition it was still building further up, and failed. Such a reference now stays as it is,
  for that schema's own hook to hold as it is finished.
- **A recursive discriminated union lost its tag.** Pydantic settles a deferred discriminator by
  taking it out of the union's metadata, which held copies shared, so all but one copy tried
  every member and reported every member's errors. Each held copy now has metadata of its own.
- **The machinery check missed a literal `getattr` and flagged ordinary code.** It now refuses
  `getattr(terp.core, "timestamps")` and the module's dotted name written as a literal, as
  `importlib` and `sys.modules` are handed it. An attribute called `timestamps` counts only on a
  name the file binds to `terp.core`, so `self.core.timestamps` is the app's own. A package's
  namespace mapping, `vars(terp.core)`, is recorded as a residual.

The fourth round, of the third rework:

- **Judging a nested class first was wrong four ways.** It validated a stand-in copy of the
  class's fields before the class's own validator, so the class's validators and default
  factories ran twice, and a before validator that rewrites its input in place, turning cents
  into a decimal, did it twice: 1250 became 0.125, not 12.5. A union of such classes picked a
  different member, dropping data. The stand-in had no `model_config`, so building the JSON
  schema, and with it `app.openapi()`, raised for any body that nested a plain model. And the
  class's own `__init__` was skipped. A class with its own validator is now left to it, decision
  1, and the model that is not a `BaseSchema` stays the open item it was.
- **A held definition was published under a new name.** Its reference ended in
  `:offsets-held`, and Pydantic names a JSON schema's definition after a reference with only
  its last colon's tail taken off, so a stdlib dataclass, a `TypedDict`, a type alias and a
  recursive schema each published a name carrying an id, new on every run. The held reference
  has no colon now, a schema's own reference stays its own, and the suite holds every such
  schema's JSON schema and OpenAPI document equal to an SQLModel twin's.
- **The worker's trust did not reach a nested schema.** SQLModel validates a nested
  `BaseSchema` afresh, with no validation context, so a job whose payload nested one failed in
  the worker. The trust is a context variable now, decision 2.
- **A hook from a base ahead of `BaseSchema` switched the refusal off.** The metaclass looked
  only at the class's own namespace. It now finds which class each hook resolves to.
- **The rule missed strings and attributes.** `Optional["NaiveMeansUtc"]` bound to a name, a
  field handed to `create_model` as `"NaiveMeansUtc"`, and a class attribute bound to the escape
  used through a subclass or an instance took the escape unseen. Each is refused now, decision
  5. A local that shadows a `terp.core` name no longer reads as it.
- **A declared filter took a naive bound given as text,** and compared it as text, so on SQLite
  it matched the wrong rows. It reads it first now, decision 3.
- **Smaller ones.** A union member was named without the config it is read under, so a str in it
  lost its `constrained-str`; it is named under it now. The refusal's and the escape's nodes are
  known only around a timestamp, so the refusal's function declared in front of anything else
  is the app's own validator, and what it stands in front of is held. The refusal of a plain
  choice of a recursive discriminated union went with the stand-in.

## Consequences

- **A client that sends a bare local time breaks.** It gets a 422 that says what to send, instead
  of being stored off by its offset. That is a breaking change for that client, and the
  CHANGELOG's upgrade notes say so, with the other text the refusal now judges.
- **An app with a sender that truly sends UTC without an offset** declares the escape on that one
  field, with the reason, in the same change.
- **A filter that took a calendar day on a timestamp column refuses it** until the filter
  declares its zone. That is a breaking change for its callers, in the same release as decision
  1's.
- **A form with a `datetime-local` control turns the lint red.** `DateTimeInput` replaces it,
  and sends what the API takes.
