# 0190 — A field declares itself personal, and what writes a record reads it

- **Status:** Accepted and implemented in 0.35.0. `terp.core.Personal` declares a field;
  the log, the audit trail, the framework's database-refusal context, validation errors and
  event and job definitions read the declaration. Held by
  `tests/architecture/test_personal_data.py` (each reader, path by path),
  `tests/architecture/test_structured_logs_served.py` (a production uvicorn process whose
  whole output holds no declared value) and the `personal_fields_are_declared` rule
  (`tests/architecture/test_arch_harness.py`). The rule's catalog entry is in the
  unreleased terp-spec 0.40.0, so it waits in `_AWAITING_SPEC_RELEASE` until the pin moves.
- **Date:** 2026-10-23. 0182 and 0183 are reserved for other records; 0184 to 0189 are taken.
- **Relates:** completes [ADR 0188](0188-every-log-line-is-a-record-of-one-versioned-schema.md)
  decision 6, which left personal data to "a separate, later decision"; amends
  [ADR 0005](0005-security-middleware-and-structured-logging.md) and
  [ADR 0006](0006-cross-cutting-controls-and-opinionation-policy.md) once more (what
  redaction covers); extends [ADR 0007](0007-audit-auto-emit-and-the-audit-seam.md) (the
  audit trail's central redaction) and [ADR 0008](0008-event-bus-catalog-and-typed-emit.md)
  (event visibility); follows [ADR 0133](0133-a-reference-declares-what-a-delete-of-its-target-does.md)
  in shape: a `Field`-style declaration, recorded where both the model and plain database
  metadata can read it, with a rule that refuses the undeclared form. Supersedes nothing.

---

## Context

ADR 0188 made the log redact secrets, and said plainly that it recognised nothing else. A
secret has a name or a shape a pattern can find: a key called `token`, a `Bearer` value, a
URL's password. An email address, a phone number or a date of birth has neither. It is a
`str` or a `date` like every other, and the one place that knew which field held one was
the model that declared it, which recorded the fact nowhere.

So personal data reached a production log by every route a model's data travels:

1. **A model handed to the log.** `log.info("saved %s", customer)`, a model in `extra=` or
   in an `AppError`'s `log_context`, rendered every field.
2. **A model rendered into text first.** An f-string, or an exception message built from a
   model, carried every field into the message and into the traceback.
3. **The framework's own refusal of a duplicate.** A unique constraint becomes a 409 whose
   `log_context["integrity_error"]` is SQLAlchemy's message, which repeats the statement's
   parameters, and on PostgreSQL the database's own detail repeats the key:
   `Key (email)=(...) already exists`. In any app with a unique address column, a signup
   with an address that is already taken wrote the address into the log.
4. **A validation error.** Pydantic's message repeats the refused input
   (`input_value='...'`); one raised inside a service is a traceback.
5. **The audit trail.** A payload was redacted for secrets and stored as given.
6. **Events.** `EventVisibility.PUBLIC` says a payload is safe to surface outward and
   `RESTRICTED` that it may carry personal data, both as advice nothing checked.

And there are readers of this fact still to come. A tool that reads a deployed app's log
for an operator, or forwards what it finds off the host, has to be able to say that the
log carries no declared personal value. A copy of a production database that a developer
may work on has to know which columns to anonymise, from the database's metadata alone.

## Decision

**1. One declaration: `Personal`, which is `Field` with one more fact.**

```python
class Customer(BaseTable, table=True):
    email: str = Personal(max_length=320, index=True, unique=True)

class CustomerRead(BaseSchema):
    id: uuid.UUID
    email: str = Personal()
```

Every keyword goes to `sqlmodel.Field` unchanged. The fact is recorded twice, once for each
kind of reader: in the field's metadata, which pydantic carries into every subclass and
which `personal_fields(model)` reads from any model, table or schema; and in a table
column's `info`, which `personal_columns(metadata)` reads from database metadata without
the model class. Neither reaches the DDL or the JSON schema, so adopting the declaration
costs no migration and changes no API contract.

A call on the value side, rather than an `Annotated[str, Personal]` marker, because it is
how this codebase already declares a field (`Field(max_length=...)`, `Ref(...)`): the line
that declares the field says what it is, and a source reader (the rule in decision 8) sees
it there. An annotation can be aliased (`Email = Annotated[...]`) into a module the
reader never opens. `json_schema_extra` was the other carrier on offer and was refused:
it would publish the fact in the OpenAPI document, and a `Field` that sets its own extras
would silently drop it. (A `Personal(...)` inside `Annotated` is read as well; it is not
taught.)

Each declaration stands on its own. A schema that redeclares `email: str` plainly has
redeclared it as not personal: pydantic does not carry a field's metadata across a
redeclaration, and the rule does not pretend it does. That is why the schemas are declared
too, and why the rule reads every model that declares the field.

**2. A Terp model renders `[PERSONAL]` in place of each declared field, wherever it is
rendered.** `BaseTable` and `BaseSchema` mask their own `repr` and `str`, so the mask holds
where the log never sees a model object: an f-string, an exception's message, a traceback,
a third-party printer. Any other pydantic model the log is handed is rendered the same way
by the log itself. The rendering keeps pydantic's own shape (`Customer(email=[PERSONAL],
note='vip')`), so a line reads as it did, minus the values it may not hold.

**3. The log reads the declaration by model and by name.** A model in an argument, the
message, `extra=` or `log_context`, at any depth, is rendered as decision 2 says. And every
field name a Terp model declares personal is collected (`personal_field_names()`), so a
value handed over under such a name (`log_context={"email": ...}`, `extra={"phone": ...}`,
a mapping argument) is `[PERSONAL]` too. A mapping carries no model to ask; the name is
the only evidence it has, and a name declared personal anywhere in the app is treated as
personal everywhere in its log. The failure this chooses is over-redaction: a key `email`
holding something that is not a person's address is withheld anyway.

Names are collected from classes built on `BaseTable`, `BaseSchema` and `BaseUpdateSchema`,
which is the convention every module follows. A plain `SQLModel` is masked when it is
rendered; its names are not collected.

The access line needs nothing: ADR 0188 built it from the route template, ids and labels,
never from the requested path or query string, so it is held by construction, and a test
sends a personal value in the query string to show it.

**4. A database's refusal loses the values of the rows it was about.** The 409's
`integrity_error` context is built from the rows in flight, the row being written and every
row the session is about to flush, and each declared personal value they hold is
replaced in the text, longest first, so a value inside another goes with it. By value,
because the text has no structure a name could key on; precise, because the values are
those rows' own.

**5. A model that declares a personal field hides its input in a validation error's text.**
It is configured with `hide_input_in_errors` when the class is created. The structured form
of the error keeps the input, and that is what FastAPI builds a 422 from, so the client
that sent a value still sees it; a traceback no longer does.

**6. The audit trail keeps each declared field's key and loses its value.** Redacted, not
omitted. The trail answers who changed what: that the address changed is evidence, the
address itself is not needed for it, and the row holds it for as long as the row exists. A
trail that copied the value would be the one place it outlived the row, which is the place
an erasure has to reach and usually cannot, because the trail is append-only. A model in a
payload is stored as its JSON dump with its declared fields withheld. There is no setting
for this: keeping personal values in the trail is a retention decision of its own, not a
switch on redaction.

**7. Events and jobs: a `PUBLIC` payload cannot declare a personal field, and
`redact_personal` is the copy that leaves the process.** An event or job payload inside the
process is not redacted: a handler that welcomes a new customer needs the address, and an
outbox row is the app's own data in the app's own database. What `PUBLIC` promises, safe to
surface outward, is contradicted by a declared personal field, so `EventDefinition`
and `JobDefinition` refuse the pair where they are declared, at import. `redact_personal`
is the shared function for any copy that may leave the process: a model becomes its JSON
dump with declared fields withheld, a mapping keeps its keys and loses the values under
declared names, and the payload's schema can be passed so a plain model's fields count. The
audit trail uses it today; a relay that forwards events off the host uses it when it is
built.

**8. The rule `personal_fields_are_declared` makes the declaration hard to forget.** A model
field whose name says it holds personal data is declared `Personal`, or carries the
justified opt-out marker saying why it is not: an organisation's support address is not a
person's. The marker is the not-personal declaration with its reason, counted in the
escape-hatch budget like every other.

The vocabulary is short on purpose, and it is a review aid rather than a definition of
personal data: names that hold a person's data in nearly every app they appear in. An email
address, a phone number, a date of birth, a national identifier, a person's name, a home
address. The noun must be the name's last words, so `contact_email` is in it and
`email_verified` is not. `postcode`, a bare `address` and a bare `name` belong to a company
as often as to a person and are left out; a field outside the vocabulary is declared by
hand, and the guide says so.

The rule applies to application roots only, because the declaration is `terp.core`'s. The
three rules that read a field's keywords (the length cap, a unique column on a
soft-deletable table, an undeclared foreign key) read `Personal` as they read `Field`, so
the declaration is no way around any of them.

Its runtime classification is `not-applicable`. The running app can see a declared field,
but the other answer the rule accepts is a comment: at runtime a field justified as not
personal is indistinguishable from one nobody looked at, so a runtime check could only
refuse every justified opt-out. The runtime protection is constructive instead: everything
in decisions 2 to 7.

**9. The framework declares its own.** The identity capability's `User.email` and the email
fields of the auth, identity, users and groups schemas are `Personal`. No migration: the
column's DDL is unchanged.

## Consequences

- A refused signup with a taken address no longer writes the address. A model logged the
  way the guide says to log it writes its ids and its ordinary fields, and `[PERSONAL]`.
- `repr` of a Terp model with a declared field shows `[PERSONAL]` everywhere, including a
  failing test's assertion output and a debugger's variable view. Compare the field, not
  the repr.
- A validation error raised from such a model no longer shows its input in its text.
- A log key with a declared field's name is withheld whatever it holds.
- The collected names are process-wide and grow as classes are defined; a test that
  declares a field adds its name for the rest of that process.
- An app that upgrades gets a `personal_fields_are_declared` finding for each vocabulary
  field it has not declared. Each is fixed with `Personal(...)` in place of `Field(...)`,
  or a justified marker. The framework's own models carry no marker.
- `personal_columns()` gives a database copy the columns to anonymise; nothing anonymises
  one yet.

## Not covered

- **A value that has stopped being a field.** `f"{customer.email}"` is a string, and so is
  `customer.email` passed to a log call on its own; nothing marks either. The guide says to
  log the model or its id. A static check of a declared field's attribute inside a log call
  is a possible later rule.
- **An `AppError`'s message.** It is the text the client receives, and it is logged as
  written; a message built from a bare personal value is free text like any other.
- **A plain model's names.** Decision 3: masked when rendered, not collected.
- **A personal field nested inside a `PUBLIC` payload's nested model.** The refusal reads
  the payload schema's own fields.
- **What the API returns.** The declaration changes no response: a client allowed to read a
  customer reads the address.
- **Anonymising a database copy, and a relay that forwards events off the host.** Both
  read this declaration and are separate work.
