"""Timestamp text carries its UTC offset (ADR 0206).

A value with no offset names no instant: ``2026-11-06T10:00:00`` is ten in the morning in
whichever zone its writer meant. Stored as UTC, which is what ``UtcDateTime`` does with a
naive value, it puts a writer one zone east of UTC an hour off, and nothing says so. The
published contract already rules such a value out: a ``datetime`` field is published as
``format: date-time``, RFC 3339's production, whose offset is not optional.

So every timestamp a ``BaseSchema`` reads *as text* must carry its offset. The schema's hook
runs :func:`hold_timestamps_to_their_offset` over the schema Pydantic builds, which puts
:func:`refuse_timestamp_text_without_offset` in front of every ``datetime`` in it, following
every definition the schema refers to. That covers wherever Pydantic validates one for the
schema: a field, an item of a list or tuple, a value of a mapping, a member of a union, a type
alias, a ``NewType``, a stdlib dataclass, a ``TypedDict``, and a nested ``BaseSchema``, under
whatever name Pydantic reads the value by. A nested model that brings its own complete
Pydantic validator (a plain ``BaseModel``, a Pydantic dataclass) would read a timestamp in it
with that validator, unjudged, so a schema that nests one holding a timestamp is refused when
it is defined. A request body is refused with a 422 at the value's place, and so is a realtime
message a client sends, and text the app's own code hands a schema. Every such value is named
in one error.

What is not text is not judged. A ``datetime`` object reaching a schema was built by the
server, read back from a row or computed in code, and a number is a Unix time, which is UTC.
So a response model built from rows validates exactly as before. The job worker reads back the
payload text the framework wrote at enqueue under a validation context the refusal trusts. That
context, like the escape's mark, is an object compared by identity, so no string an app writes
is it, and reaching it means importing this module, which the rule refuses to an app.

A declared filter is the other door (:mod:`terp.core.filtering`). FastAPI has parsed its
parameter into a ``datetime`` before it gets there, so :func:`require_offset` refuses a naive
bound, a 400 that names the filter.

The framework's one way around both is :data:`NaiveMeansUtc`, a type that reads a value with
no offset as UTC, for a sender known to send UTC without saying so. The
``request_timestamps_carry_their_offset`` rule refuses each use of it unless the line carries
the rule's marker, which the app's escape-hatch budget counts, so taking it is a decision a
reviewer sees.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, cast

from pydantic import GetCoreSchemaHandler, TypeAdapter, ValidationError, ValidationInfo
from pydantic_core import CoreSchema, PydanticCustomError, SchemaError, SchemaValidator, core_schema

from terp.core.errors import ValidationFailedError

#: What a refusal tells the writer, in a body and in a filter alike.
OFFSET_REQUIRED = (
    "A date and time needs its UTC offset, for example 2026-11-06T10:00:00Z or "
    "2026-11-06T11:00:00+01:00"
)

#: Keys of a schema node whose values are data or settings, never a schema to walk into.
_NOT_SCHEMAS = frozenset({"metadata", "serialization", "default", "expected", "ref", "cls", "config"})

#: The node kinds pydantic-core validates with a class's own prebuilt validator, when the
#: class is complete, whatever schema it is handed for them.
_PREBUILT = frozenset({"model", "dataclass"})

_DATETIME: TypeAdapter[datetime] = TypeAdapter(datetime)

#: The validation-context key under which the framework reads back text it wrote itself. An
#: object compared by identity, so no string an app writes is it, and reaching it means
#: importing this module, which the rule refuses to an app however it is spelled.
_SERVER_TEXT = object()


def _server_text_context() -> dict[object, bool]:
    """The validation context that marks text the framework wrote itself (a job's payload)."""
    return {_SERVER_TEXT: True}


def _as_utc_when_naive(value: datetime) -> datetime:
    """The escape's own validator, whose identity marks the escape's schema node."""
    return value if value.utcoffset() is not None else value.replace(tzinfo=UTC)


def refuse_timestamp_text_without_offset(value: object, info: ValidationInfo) -> object:
    """Refuse timestamp text that names no instant; hand everything else to the type.

    It runs in front of every ``datetime`` a ``BaseSchema`` validates. Text that reads as a
    date and time without an offset is refused, error type ``timestamp_offset_required``. Text
    that is no timestamp at all goes on to the type, whose own error says so. An object and a
    number go on unjudged, and so does text the framework wrote itself.
    """
    if not isinstance(value, str | bytes | bytearray):
        return value
    context = info.context
    if isinstance(context, dict) and context.get(_SERVER_TEXT) is True:
        return value
    try:
        parsed = _DATETIME.validate_python(value)
    except ValidationError:
        return value
    if parsed.utcoffset() is None:
        raise PydanticCustomError("timestamp_offset_required", OFFSET_REQUIRED)
    return value


def _function_of(schema: dict[str, Any]) -> object:
    function = schema.get("function")
    return function.get("function") if isinstance(function, dict) else None


def _is_judged(schema: dict[str, Any]) -> bool:
    return (
        schema.get("type") == "function-before"
        and _function_of(schema) is refuse_timestamp_text_without_offset
    )


def _is_escape(schema: dict[str, Any]) -> bool:
    return schema.get("type") == "function-after" and _function_of(schema) is _as_utc_when_naive


def _label(member: Any) -> str | None:
    """The name a union gives *member* in an error's location, as Pydantic names it."""
    try:
        return SchemaValidator(member).title
    except SchemaError:  # a member that refers to a definition cannot stand alone
        return member.get("ref") if isinstance(member, dict) else None


class _Holding:
    """One walk over a schema: the held copies of its definitions, and what it refused."""

    def __init__(self, handler: GetCoreSchemaHandler, owner: type, judged: type) -> None:
        self.handler = handler
        self.owner = owner
        self.judged = judged
        self.refs: dict[str, str] = {}
        self.definitions: list[CoreSchema] = []

    def walk(self, schema: Any) -> Any:
        if isinstance(schema, list):
            held_items = [self.walk(item) for item in schema]
            return schema if all(a is b for a, b in zip(held_items, schema, strict=True)) else held_items
        if isinstance(schema, tuple):
            return tuple(self.walk(item) for item in schema)
        if not isinstance(schema, dict):
            return schema
        kind = schema.get("type")
        if kind is None:
            # A mapping of names to schemas (a model's fields, a tagged union's choices): every
            # key is a name, never a setting, so every value is walked.
            held_values = {key: self.walk(value) for key, value in schema.items()}
            return schema if all(held_values[key] is schema[key] for key in schema) else held_values
        if _is_judged(schema) or _is_escape(schema):
            return schema
        if kind == "datetime":
            return core_schema.with_info_before_validator_function(
                refuse_timestamp_text_without_offset, schema
            )
        if kind == "definition-ref":
            return self._reference(schema)
        if kind == "union":
            return self._union(schema)
        if kind in _PREBUILT:
            return self._nested(schema)
        return self._node(schema)

    def _node(self, schema: dict[str, Any]) -> dict[str, Any]:
        held_values = {
            key: value if key in _NOT_SCHEMAS else self.walk(value) for key, value in schema.items()
        }
        return schema if all(held_values[key] is schema[key] for key in schema) else held_values

    def _reference(self, schema: dict[str, Any]) -> dict[str, Any]:
        ref = schema["schema_ref"]
        if ref not in self.refs:
            self.refs[ref] = f"{ref}:offsets-held"
            target = self.handler.resolve_ref_schema(
                cast("core_schema.DefinitionReferenceSchema", schema)
            )
            held = self.walk(target)
            if held is target:
                self.refs[ref] = ref
            else:
                self.definitions.append({**held, "ref": self.refs[ref]})
        held_ref = self.refs[ref]
        return schema if held_ref == ref else {**schema, "schema_ref": held_ref}

    def _union(self, schema: dict[str, Any]) -> dict[str, Any]:
        choices: list[Any] = []
        changed = False
        for choice in schema["choices"]:
            member, label = choice if isinstance(choice, tuple) else (choice, None)
            held = self.walk(member)
            if held is not member:
                changed = True
                label = label or _label(member)
            choices.append((held, label) if label else held)
        return {**schema, "choices": choices} if changed else schema

    def _nested(self, schema: dict[str, Any]) -> dict[str, Any]:
        cls = schema.get("cls")
        if cls is self.owner:
            return self._node(schema)  # the schema being held
        if isinstance(cls, self.judged):
            return schema  # a held schema's own class: its validator judges already
        held = self._node(schema)
        if held is schema:
            return schema
        if isinstance(cls, type) and cls.__dict__.get("__pydantic_complete__") is True:
            raise TypeError(
                f"{self.owner.__name__} nests {cls.__qualname__}, which brings its own Pydantic "
                "validator, and that validator reads a timestamp in it without judging its UTC "
                f"offset (ADR 0206); derive {cls.__qualname__} from BaseSchema, or type that "
                "timestamp NaiveMeansUtc if its sender sends UTC without saying so"
            )
        return held


def hold_timestamps_to_their_offset(
    schema: CoreSchema, handler: GetCoreSchemaHandler, *, owner: type, judged: type
) -> CoreSchema:
    """*schema* with every ``datetime`` it validates judged by the refusal.

    ``BaseSchema``'s schema hook runs this over the schema Pydantic builds for each subclass
    (*owner*), following each definition the schema refers to into a held copy, so the refusal
    sits wherever Pydantic validates a timestamp for it. A class whose metaclass is *judged* is
    a ``BaseSchema``, whose own schema is held already. The escape's node is left as it is.
    """
    holding = _Holding(handler, owner, judged)
    held: CoreSchema = holding.walk(schema)
    if holding.definitions:
        return core_schema.definitions_schema(held, holding.definitions)
    return held


class _NaiveMeansUtc:
    """The escape's mark: read a value without an offset as UTC, and stay unjudged."""

    __slots__ = ()

    def __get_pydantic_core_schema__(
        self, source: Any, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        return core_schema.no_info_after_validator_function(_as_utc_when_naive, handler(source))

    def __repr__(self) -> str:
        return "NaiveMeansUtc"


NaiveMeansUtc = Annotated[datetime, _NaiveMeansUtc()]
"""A timestamp that reads a value with no offset as UTC: the escape from ADR 0206.

Declare it on a field or a query parameter whose sender is known to send UTC without an
offset. The value arrives aware, in UTC, so a declared filter takes it too. Every use is
refused by the ``request_timestamps_carry_their_offset`` rule unless its line carries
``# arch-allow-request-timestamps-carry-their-offset: <reason>``.
"""


def require_offset(name: str, value: datetime) -> None:
    """Refuse a declared filter's bound that carries no UTC offset, naming the filter."""
    if value.utcoffset() is None:
        raise ValidationFailedError(
            f"Filter {name!r} needs a date and time with its UTC offset, for example "
            "2026-11-06T10:00:00Z."
        )


__all__ = [
    "OFFSET_REQUIRED",
    "NaiveMeansUtc",
    "hold_timestamps_to_their_offset",
    "refuse_timestamp_text_without_offset",
    "require_offset",
]
