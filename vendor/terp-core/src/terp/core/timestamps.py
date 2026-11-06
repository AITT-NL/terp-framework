"""Timestamp text carries its UTC offset (ADR 0206).

A value with no offset names no instant: ``2026-11-06T10:00:00`` is ten in the morning in
whichever zone its writer meant. Stored as UTC, which is what ``UtcDateTime`` does with a
naive value, it puts a writer one zone east of UTC an hour off, and nothing says so. The
published contract already rules such a value out: a ``datetime`` field is published as
``format: date-time``, RFC 3339's production, whose offset is not optional.

So every timestamp a ``BaseSchema`` reads *as text* must carry its offset. The schema's hook
runs :func:`hold_timestamps_to_their_offset` over the schema Pydantic builds, which puts
:func:`refuse_timestamp_text_without_offset` in front of every ``datetime`` the schema reads
itself, following every definition it refers to: a field, an item of a list or tuple, a value
of a mapping, a member of a union, a type alias, a ``NewType``, a stdlib dataclass and a
``TypedDict``, under whatever name Pydantic reads the value by. A nested ``BaseSchema`` holds
its own the same way. A class that brings its own Pydantic validator (a plain ``BaseModel``, a
Pydantic dataclass, a table, a root model) reads its fields with that validator, which Pydantic
uses whatever schema surrounds the class, so it is left to it, as a request model that is not
a ``BaseSchema`` is. A request body is refused with a 422 at the value's place, and so is a
realtime message a client sends, and text the app's own code hands a schema. Every such value
is named in one error.

What is not text is not judged. A ``datetime`` object reaching a schema was built by the
server, read back from a row or computed in code, and a number is a Unix time, which is UTC.
So a response model built from rows validates exactly as before. The job worker reads back the
payload text the framework wrote at enqueue while :func:`_reading_server_text` is in force,
which every schema the read reaches trusts, a nested one included. Reaching it means
importing this module, which the rule refuses to an app.

A declared filter is the other door (:mod:`terp.core.filtering`). FastAPI has parsed its
parameter into a ``datetime`` before it gets there, so :func:`require_offset` refuses a naive
bound, a 400 that names the filter, and reads a bound the app's own code gives as text first.

The framework's one way around both is :data:`NaiveMeansUtc`, a type that reads a value with
no offset as UTC, for a sender known to send UTC without saying so. The
``request_timestamps_carry_their_offset`` rule refuses each use of it unless the line carries
the rule's marker, which the app's escape-hatch budget counts, so taking it is a decision a
reviewer sees.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, date, datetime
from typing import Annotated, Any, cast

from pydantic import BaseModel, GetCoreSchemaHandler, TypeAdapter, ValidationError, ValidationInfo
from pydantic.dataclasses import is_pydantic_dataclass
from pydantic_core import CoreSchema, PydanticCustomError, SchemaError, SchemaValidator, core_schema

from terp.core.errors import ValidationFailedError

#: What a refusal tells the writer, in a body and in a filter alike.
OFFSET_REQUIRED = (
    "A date and time needs its UTC offset, for example 2026-11-06T10:00:00Z or "
    "2026-11-06T11:00:00+01:00"
)

#: Keys of a schema node whose values are data or settings, never a schema to walk into.
_NOT_SCHEMAS = frozenset(
    {"metadata", "serialization", "default", "expected", "ref", "cls", "config", "custom_error_context"}
)

#: What a held copy of a definition is referred to by: the original's reference and this. It
#: has no colon, so Pydantic, which drops what follows a reference's last colon when it names
#: a definition in a JSON schema, names the copy as it names the original.
_HELD = "-offsets-held"

_DATETIME: TypeAdapter[datetime] = TypeAdapter(datetime)

#: Whether the framework is reading back text it wrote itself. A context variable, so every
#: schema the read reaches sees it, a nested one that SQLModel validates afresh included, and
#: nothing else does; reaching it means importing this module, which the rule refuses to an app.
_SERVER_TEXT: ContextVar[bool] = ContextVar("terp_server_text", default=False)


@contextmanager
def _reading_server_text() -> Iterator[None]:
    """Trust the text read while this is in force: the framework wrote it (a job's payload)."""
    token = _SERVER_TEXT.set(True)
    try:
        yield
    finally:
        _SERVER_TEXT.reset(token)


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
    if not isinstance(value, str | bytes | bytearray) or _SERVER_TEXT.get():
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


def _around_a_timestamp(schema: dict[str, Any]) -> bool:
    inner = schema.get("schema")
    return isinstance(inner, dict) and inner.get("type") == "datetime"


def _is_judged(schema: dict[str, Any]) -> bool:
    """The refusal's own node: the refusal in front of a timestamp, and nothing else."""
    return (
        schema.get("type") == "function-before"
        and _function_of(schema) is refuse_timestamp_text_without_offset
        and _around_a_timestamp(schema)
    )


def _is_escape(schema: dict[str, Any]) -> bool:
    """The escape's own node: its validator behind a timestamp, and nothing else."""
    return (
        schema.get("type") == "function-after"
        and _function_of(schema) is _as_utc_when_naive
        and _around_a_timestamp(schema)
    )


def _reads_its_own_fields(cls: object) -> bool:
    """Whether *cls* brings its own Pydantic validator: a model, or a Pydantic dataclass.

    Pydantic validates such a class with that validator whatever schema surrounds it. A
    ``BaseSchema`` is one, and its validator is held already; a stdlib dataclass is not, and
    the schema around it validates it.
    """
    return isinstance(cls, type) and (issubclass(cls, BaseModel) or is_pydantic_dataclass(cls))


def _schemas_in(schema: dict[str, Any]) -> Iterator[tuple[str, Any]]:
    """The keys of *schema* whose values are schemas, each with its value.

    A mapping of names to schemas (a model's fields, a tagged union's choices) has no kind of
    its own: every key is a name, never a setting, so every value is a schema. A field named
    "type" is a schema under that key, not a kind, which is how such a mapping is told from a
    node. A node's settings and data are not schemas.
    """
    node = isinstance(schema.get("type"), str)
    return ((key, value) for key, value in schema.items() if not (node and key in _NOT_SCHEMAS))


def _own_metadata(node: dict[str, Any]) -> dict[str, Any]:
    """*node*, a held copy, with metadata of its own.

    Pydantic finishes a deferred discriminator by taking it out of the union's metadata, so a
    copy that shared the original's would leave every other copy a plain union.
    """
    metadata = node.get("metadata")
    if isinstance(metadata, dict):
        node["metadata"] = dict(metadata)
    return node


class _Holding:
    """One walk over a schema: the held copies of the definitions it reads itself."""

    def __init__(self, handler: GetCoreSchemaHandler, owner: type, owner_ref: object) -> None:
        self.handler = handler
        self.owner = owner
        self.owner_ref = owner_ref
        self.refs: dict[str, str] = {}
        self.configs: list[dict[str, Any]] = []
        self.definitions: list[CoreSchema] = []

    def walk(self, schema: Any) -> Any:
        if isinstance(schema, list | tuple):
            held_items = [self.walk(item) for item in schema]
            if all(a is b for a, b in zip(held_items, schema, strict=True)):
                return schema
            return held_items if isinstance(schema, list) else tuple(held_items)
        if not isinstance(schema, dict):
            return schema
        kind = schema.get("type")
        if not isinstance(kind, str):
            return self._node(schema)  # a mapping of names to schemas, every value walked
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
        if kind in ("model", "dataclass") and schema.get("cls") is not self.owner:
            if _reads_its_own_fields(schema.get("cls")):
                return schema  # a BaseSchema holds its own; any other such class reads its own
        return self._node(schema)

    def _node(self, schema: dict[str, Any]) -> dict[str, Any]:
        config = schema.get("config") if isinstance(schema.get("type"), str) else None
        if isinstance(config, dict):
            self.configs.append(config)
        try:
            held_values = {key: self.walk(value) for key, value in _schemas_in(schema)}
        finally:
            if isinstance(config, dict):
                self.configs.pop()
        if all(held is schema[key] for key, held in held_values.items()):
            return schema
        return _own_metadata({**schema, **held_values})

    def _reference(self, schema: dict[str, Any]) -> dict[str, Any]:
        ref = schema["schema_ref"]
        if ref == self.owner_ref:
            return schema  # Pydantic keeps the held schema under the owner's own reference
        if ref not in self.refs:
            try:
                target = self.handler.resolve_ref_schema(
                    cast("core_schema.DefinitionReferenceSchema", schema)
                )
            except LookupError:
                # A definition Pydantic is still building further up, as when two schemas refer
                # to each other: a schema's own hook holds it as it is finished, so it stays.
                self.refs[ref] = ref
                return schema
            self.refs[ref] = f"{ref}{_HELD}"
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
                label = label or self._label(member)
            choices.append((held, label) if label else held)
        return _own_metadata({**schema, "choices": choices}) if changed else schema

    def _label(self, member: Any) -> str | None:
        """The name a union gives *member* in an error's location, as Pydantic names it.

        Pydantic names a member by the validator it builds for it, so the member, as Pydantic
        built it, is built on its own, under the config it is read with and with every definition
        it refers to. Where a member refers back to the schema it is in, Pydantic writes ``...``
        for that schema; built on its own, the member names it by its name.
        """
        try:
            definitions = self._definitions_of(member)
            if member.get("type") == "definition-ref":
                member = definitions[member["schema_ref"]]
            standalone = core_schema.definitions_schema(
                member, [{**target, "ref": ref} for ref, target in definitions.items()]
            )
            # The config a member is read under shapes its name (a stripped ``str`` is a
            # ``constrained-str``); its title would name the member after the class instead.
            config = {key: value for key, value in (self.configs[-1] if self.configs else {}).items() if key != "title"}
            return SchemaValidator(standalone, cast("core_schema.CoreConfig", config)).title
        except (LookupError, SchemaError):  # it refers to a definition still being built
            return None

    def _definitions_of(self, schema: Any) -> dict[str, Any]:
        """Every definition *schema* refers to, and every one those refer to, by reference."""
        found: dict[str, Any] = {}
        pending = [schema]
        while pending:
            node = pending.pop()
            if isinstance(node, list | tuple):
                pending.extend(node)
            elif isinstance(node, dict):
                ref = node.get("schema_ref")
                if node.get("type") == "definition-ref" and ref not in found:
                    found[ref] = self.handler.resolve_ref_schema(
                        cast("core_schema.DefinitionReferenceSchema", node)
                    )
                    pending.append(found[ref])
                pending.extend(value for _, value in _schemas_in(node))
        return found


def hold_timestamps_to_their_offset(
    schema: CoreSchema, handler: GetCoreSchemaHandler, *, owner: type
) -> CoreSchema:
    """*schema* with every ``datetime`` it reads itself judged by the refusal.

    ``BaseSchema``'s schema hook runs this over the schema Pydantic builds for each subclass
    (*owner*), following each definition the schema refers to into a held copy, so the refusal
    sits wherever the schema validates a timestamp itself. A class that brings its own Pydantic
    validator is left as it is, and so is the escape's node.
    """
    holding = _Holding(handler, owner, schema.get("ref"))
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


def _names_no_instant(name: str) -> ValidationFailedError:
    return ValidationFailedError(
        f"Filter {name!r} needs a date and time with its UTC offset, for example "
        "2026-11-06T10:00:00Z."
    )


def require_offset(name: str, value: datetime | date | str | bytes | bytearray) -> datetime:
    """A declared filter's bound as the instant it names, refused, naming the filter, if none.

    A bound the app's own code gives as text is read as a date and time first, as a request's
    would be, so text that is none, and text without a UTC offset, are refused alike. So is a
    calendar day, which names no instant until it names the zone whose day it is.
    """
    if isinstance(value, str | bytes | bytearray):
        try:
            value = _DATETIME.validate_python(value)
        except ValidationError as exc:
            raise _names_no_instant(name) from exc
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise _names_no_instant(name)
    return value


__all__ = [
    "OFFSET_REQUIRED",
    "NaiveMeansUtc",
    "hold_timestamps_to_their_offset",
    "refuse_timestamp_text_without_offset",
    "require_offset",
]
