# `backend/request_timestamps_carry_their_offset`

**A timestamp a client sends carries its UTC offset**

> Generated from the catalog by `tools/generate_rule_docs.py` — do not
> edit by hand; the parity test holds this page to
> `packages/backend/arch/src/terp/arch/catalog/backend/request_timestamps_carry_their_offset.json`.

## Why this rule exists

A date and time without a UTC offset names no instant: ten in the morning is a different moment in every zone. Stored as if it were UTC, it puts a writer in any other zone off by that zone's offset, and nothing reports it. The published API contract already asks for the offset, since a date-time there is the RFC 3339 form, whose offset is required. So timestamp text without one is refused wherever a request schema reads it, and a declared filter refuses a bound without one; the refusal names the fix. Reading a value without an offset as UTC, for a sender known to send UTC without saying so, is the framework's one way around it, and it is an escape a person decides and a reviewer sees. So is an app's own validator that reads the text before the timestamp's type does, since it can read the time in a zone of its own choosing. The wall time of a named zone needs neither: the zone names the instant, and the framework's type for it refuses a time the clocks skip or repeat.

## How Terp realises this

The rule fails closed by name. Every reference to NaiveMeansUtc is refused: as a name, as an attribute (core.NaiveMeansUtc, terp.core.NaiveMeansUtc), through getattr with that literal name, and in a string Pydantic evaluates as a type, such as a quoted annotation, a forward reference in Optional["NaiveMeansUtc"] or a field handed to create_model. So is every name the file binds to it by an import alias, an assignment or a type alias, at each use where that binding is the one in scope, and a class attribute bound to it at each use of that attribute's name, through the class, a subclass or an instance. A class or a re-export of that name from anywhere counts too, and so does reaching terp.core.timestamps, the boundary's own module, however it is spelled (an import of it, from terp.core import timestamps, an attribute of the terp.core package or a getattr of it by that literal name, and its dotted name written as a literal, as importlib and sys.modules are handed it); an attribute called timestamps on anything else, or on a local that shadows the package's name, is the app's own. A Literal value is text, not the escape. A plain datetime field needs nothing, and neither does a datetime query parameter forwarded to a declared filter: at run time BaseSchema refuses timestamp text without an offset wherever it reads a datetime itself, as a 422 at its place, and the filter refuses a bound without one as a 400 that names it, reading a bound given as text first (ADR 0206). The rule holds every root that ships Python, a worker as much as the app; terp.core, which defines the boundary and its escape, and terp.arch, which defines this rule and names both as the data it matches, are neither's user. An app's own validator that runs before a timestamp's type is the escape too (ADR 0207). That is a BeforeValidator, WrapValidator or PlainValidator in an Annotated type that reads a timestamp (datetime, AwareDatetime and the other datetime types, under any alias the file binds, in a union, a list or a quoted annotation), or a name bound to one, counted where that type is spelled; and a field_validator in before, wrap or plain mode, or Pydantic 1's validator with pre=True, on a field its class, or a base the same file defines, declares as a timestamp, named, as "*", or by a field name or a mode the file computes. An after validator, a validator on a field that is no timestamp (a date is a day), and a model validator, which sees the body rather than a field, are not. A wall time in a named zone is LocalTimeIn's (Annotated[datetime, LocalTimeIn("Europe/Amsterdam")]), which names the instant and refuses a time the clocks skip or repeat, so it is no escape.

## If you really need an exception

Add a justified marker on (or immediately above) the line, and record it
in your app's escape-hatch budget:

```
# arch-allow-request-timestamps-carry-their-offset: <reason>
```

An unjustified marker is itself a violation, and marker counts must
exactly match the checked-in budget (which can only shrink).

## What the check is not required to catch

A check precise enough to have no false positives has limits. This
rule's limits are recorded as data (its corpus's `RESIDUALS.json`), so
where detection ends is a statement rather than a guess:

- an alias of the escape bound in one module and imported into another under a different name counts once, where it is bound, not at each use in the other module
- a name reached through a computed attribute (getattr with a name that is not a literal, or an import made by importlib) is not resolved to the escape
- a name bound to the escape by a for loop, a with statement or an assignment expression counts where the escape is named, not at each use of that name
- the boundary's own module reached through a package's namespace (`vars(terp.core)` or its `__dict__`), or by a module name that is not a literal, is not resolved to that module
- the escape's own validator taken out of a schema that declares the escape, and declared on another field by hand, is not resolved to the escape: the rule sees the escape where it is named, and only there
- an early validator on a timestamp field that a base from another module declares is not resolved to a timestamp field, because the check resolves a base by its name within the file
- a validator of the whole model (model_validator in before or wrap mode, Pydantic 1's root_validator with pre=True) is not counted: it sees the body rather than a field, so counting it would mostly be noise (ADR 0206, Open)
- a validator a schema gets at run time (create_model's __validators__, a type whose own __get_pydantic_core_schema__ reads the text, a validator held in a name the file does not bind to a call of one) is not resolved to the escape

**These are not exemptions.** The rule governs those forms exactly as it
governs any other — a checker is simply not required to find them, so
review is the control there. The list only shrinks: closing one means
adding the corpus case that contracts it.

## Enforcement

- Checked while the app runs? Yes — the framework also enforces this while the app runs (fail closed).
- `build-time`: `terp.arch` — `check_request_timestamps_carry_their_offset`
- `runtime`: `terp.core` — `refuse_timestamp_text_without_offset`
- `runtime`: `terp.core` — `require_offset`
