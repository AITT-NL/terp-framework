"""Timestamp text carries its UTC offset (ADR 0206).

A value with no offset names no instant: ``2026-11-06T10:00:00`` is ten in the morning in
whichever zone its writer meant. Stored as UTC, which is what ``UtcDateTime`` does with a
naive value, it puts a writer one zone east of UTC an hour off, and nothing says so. The
published contract already rules such a value out: a ``datetime`` field is published as
``format: date-time``, RFC 3339's production, whose offset is not optional.

So every timestamp a ``BaseSchema`` reads *as text* must carry its offset. The schema's
hook runs :func:`hold_timestamps_to_their_offset` over the schema Pydantic builds, which puts
:func:`refuse_timestamp_text_without_offset` in front of every ``datetime`` in it. That is
wherever Pydantic validates one: a field, an item of a list, a value of a dict, a member of a
union, a nested model, under whatever alias Pydantic reads it by. A request body is refused
with a 422 at the field. So is a realtime message a client sends, and so is text the app's
own code hands a schema. Every such value is named in one error.

What is not text is not judged. A ``datetime`` object reaching a schema was built by the
server, read back from a row or computed in code, and a number is a Unix time, which is UTC.
So a response model built from rows validates exactly as before. The framework re-reads text
it wrote itself once: a job's payload, from its queue. That read passes
:func:`_server_text_context`, which the refusal trusts.

A declared filter is the other door (:mod:`terp.core.filtering`). FastAPI has parsed its
parameter into a ``datetime`` before it gets there, so :func:`require_offset` refuses a naive
bound, a 400 that names the filter.

The one way around both is :data:`NaiveMeansUtc`, a type that reads a value with no offset as
UTC, for a sender known to send UTC without saying so. The
``request_timestamps_carry_their_offset`` rule refuses each use of it unless the line carries
the rule's marker, which the app's escape-hatch budget counts, so taking it is a decision a
reviewer sees.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import GetCoreSchemaHandler, TypeAdapter, ValidationError, ValidationInfo
from pydantic_core import CoreSchema, PydanticCustomError, core_schema

from terp.core.errors import ValidationFailedError

#: What a refusal tells the writer, in a body and in a filter alike.
OFFSET_REQUIRED = (
    "A date and time needs its UTC offset, for example 2026-11-06T10:00:00Z or "
    "2026-11-06T11:00:00+01:00"
)

#: Schema metadata: a node the escape owns, and a node the refusal already judges.
_ESCAPE = "terp.timestamps.naive-means-utc"
_JUDGED = "terp.timestamps.judged"

#: Validation context: text the framework wrote itself, which it reads back unjudged.
_SERVER_TEXT = "terp.timestamps.server-text"

#: Keys of a schema node whose values are data or settings, never a schema to walk into.
_NOT_SCHEMAS = frozenset({"metadata", "serialization", "default", "expected", "ref", "cls"})

_DATETIME: TypeAdapter[datetime] = TypeAdapter(datetime)


def _server_text_context() -> dict[str, bool]:
    """The validation context that marks text the framework wrote itself (a job's payload)."""
    return {_SERVER_TEXT: True}


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


def _held(schema: Any) -> Any:
    if isinstance(schema, list):
        return [_held(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    metadata = schema.get("metadata")
    if isinstance(metadata, dict) and (metadata.get(_ESCAPE) or metadata.get(_JUDGED)):
        return schema
    if schema.get("type") == "datetime":
        return core_schema.with_info_before_validator_function(
            refuse_timestamp_text_without_offset, schema, metadata={_JUDGED: True}
        )
    if schema.get("type") == "union":
        # A union names each member in an error's location. A wrapped timestamp keeps the
        # name it had, rather than the name of the function in front of it.
        return {**schema, "choices": [_union_choice(choice) for choice in schema["choices"]]}
    return {key: value if key in _NOT_SCHEMAS else _held(value) for key, value in schema.items()}


def _union_choice(choice: Any) -> Any:
    if isinstance(choice, tuple):
        member, label = choice
        return (_held(member), label)
    if isinstance(choice, dict) and choice.get("type") == "datetime":
        return (_held(choice), "datetime")
    return _held(choice)


def hold_timestamps_to_their_offset(schema: CoreSchema) -> CoreSchema:
    """*schema* with every ``datetime`` in it judged by the refusal, the escape's left alone.

    ``BaseSchema``'s schema hook runs this over the schema Pydantic builds for each subclass,
    so the refusal sits wherever Pydantic validates a timestamp, at the place Pydantic reads
    it from. A node the escape owns is left as it is, and so is one already judged.
    """
    held: CoreSchema = _held(schema)
    return held


def _as_utc_when_naive(value: datetime) -> datetime:
    return value if value.utcoffset() is not None else value.replace(tzinfo=UTC)


class _NaiveMeansUtc:
    """The escape's mark: read a value without an offset as UTC, and stay unjudged."""

    __slots__ = ()

    def __get_pydantic_core_schema__(
        self, source: Any, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        return core_schema.no_info_after_validator_function(
            _as_utc_when_naive, handler(source), metadata={_ESCAPE: True}
        )

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
