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
whatever name Pydantic reads the value by. A nested class that brings its own complete
Pydantic validator (a plain ``BaseModel``, a Pydantic dataclass, a model the framework builds)
is validated by that validator whatever schema is handed to it, so the text it is given is
judged first, against a copy of its fields held the same way and read under its own config,
and then handed to it unchanged. A request body is refused with a 422 at the value's place,
and so is a realtime message a client sends, and text the app's own code hands a schema. Every
such value is named in one error.

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

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Annotated, Any, cast

from pydantic import GetCoreSchemaHandler, TypeAdapter, ValidationError, ValidationInfo
from pydantic_core import (
    CoreSchema,
    InitErrorDetails,
    PydanticCustomError,
    SchemaError,
    SchemaValidator,
    core_schema,
)

from terp.core.errors import ValidationFailedError

#: What a refusal tells the writer, in a body and in a filter alike.
OFFSET_REQUIRED = (
    "A date and time needs its UTC offset, for example 2026-11-06T10:00:00Z or "
    "2026-11-06T11:00:00+01:00"
)

#: The error type of a refusal, which is how a refusal is recognised.
_REFUSED = "timestamp_offset_required"

#: Keys of a schema node whose values are data or settings, never a schema to walk into.
_NOT_SCHEMAS = frozenset(
    {"metadata", "serialization", "default", "expected", "ref", "cls", "config", "custom_error_context"}
)

#: The node kinds pydantic-core validates with a class's own prebuilt validator, when the
#: class is complete, whatever schema it is handed for them.
_PREBUILT = frozenset({"model", "dataclass"})

#: What a stand-in for such a class leaves out of the class's node: the hooks the class has and
#: the stand-in does not, and what names or serialises the class rather than validating it.
_CLASS_ONLY = frozenset({"custom_init", "post_init", "generic_origin", "ref", "metadata", "serialization"})

#: Where Pydantic keeps a union's discriminator until the definitions its members need exist.
_DEFERRED_DISCRIMINATOR = "pydantic_internal_union_discriminator"

#: What a held copy of a definition is referred to by: the original's reference and this.
_HELD = ":offsets-held"

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
        raise PydanticCustomError(_REFUSED, OFFSET_REQUIRED)
    return value


class _JudgedFirst:
    """Judge what a class with its own validator is given, then hand it on unchanged.

    It wraps a stand-in for the class, whose fields are held like a schema's own, so validating
    the value against the stand-in raises a refusal wherever the class would read timestamp
    text without an offset. Only the refusals are kept: every other error is the class's own
    validator's to report, so each comes once. An instance of the class was built already, and
    its values are objects, so it goes straight on.
    """

    __slots__ = ("cls",)

    def __init__(self, cls: type) -> None:
        self.cls = cls

    def __call__(self, value: object, handler: core_schema.ValidatorFunctionWrapHandler) -> object:
        if isinstance(value, self.cls):
            return value
        try:
            handler(value)
        except ValidationError as exc:
            refused = [error for error in exc.errors() if error["type"] == _REFUSED]
            if refused:
                raise ValidationError.from_exception_data(
                    exc.title,
                    [
                        InitErrorDetails(
                            type=PydanticCustomError(_REFUSED, OFFSET_REQUIRED),
                            loc=tuple(error["loc"]),
                            input=error["input"],
                        )
                        for error in refused
                    ],
                ) from None
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


def _judged_first(schema: dict[str, Any]) -> type | None:
    """The class *schema* judges what it is given for, when it is the wrapper ``_nested`` builds."""
    if schema.get("type") != "chain":
        return None
    function = _function_of(schema["steps"][0])
    return function.cls if isinstance(function, _JudgedFirst) else None


def _is_complete(cls: object) -> bool:
    """Whether pydantic-core reuses *cls*'s own validator for its node, whatever the node holds."""
    return isinstance(cls, type) and cls.__dict__.get("__pydantic_complete__") is True


def _schemas_in(schema: dict[str, Any]) -> Iterator[tuple[str, Any]]:
    """The keys of *schema* whose values are schemas, each with its value.

    A mapping of names to schemas (a model's fields, a tagged union's choices) has no kind of
    its own: every key is a name, never a setting, so every value is a schema. A field named
    "type" is a schema under that key, not a kind, which is how such a mapping is told from a
    node. A node's settings and data are not schemas.
    """
    node = isinstance(schema.get("type"), str)
    return ((key, value) for key, value in schema.items() if not (node and key in _NOT_SCHEMAS))


def _unheld(schema: Any) -> Any:
    """*schema* as Pydantic built it, before it was held, which is what Pydantic names.

    A class judged first never sits in it inline: a schema Pydantic builds afresh, the only kind
    whose members are held a second time, refers to every class by a definition of its own.
    """
    if isinstance(schema, list | tuple):
        return type(schema)(_unheld(item) for item in schema)
    if not isinstance(schema, dict):
        return schema
    if _is_judged(schema):
        return _unheld(schema["schema"])
    if schema.get("type") == "definition-ref":
        return {**schema, "schema_ref": schema["schema_ref"].split(_HELD)[0]}
    return {**schema, **{key: _unheld(value) for key, value in _schemas_in(schema)}}


def _own_metadata(node: dict[str, Any]) -> dict[str, Any]:
    """*node*, a held copy, with metadata of its own.

    Pydantic finishes a deferred discriminator by taking it out of the union's metadata, so a
    copy that shared the original's would leave every other copy a plain union.
    """
    metadata = node.get("metadata")
    if isinstance(metadata, dict):
        node["metadata"] = dict(metadata)
    return node


def _stand_in(held: dict[str, Any]) -> dict[str, Any]:
    """*held*, a held class node, validated for a stand-in pydantic-core has no validator for.

    pydantic-core builds a stand-in's validator from the node it is handed, so it reads the
    held fields, under the class's own config. What it makes is thrown away.
    """
    cls = held["cls"]
    stand_in = type(cls.__name__, (), {"__module__": cls.__module__, "__qualname__": cls.__qualname__})
    return {**{key: value for key, value in held.items() if key not in _CLASS_ONLY}, "cls": stand_in}


class _Holding:
    """One walk over a schema: the held copies of its definitions, and what judges first."""

    def __init__(self, handler: GetCoreSchemaHandler, owner: type, judged: type) -> None:
        self.handler = handler
        self.owner = owner
        self.judged = judged
        self.refs: dict[str, str] = {}
        self.judged_first: dict[str, type] = {}
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
        if _is_judged(schema) or _is_escape(schema) or _judged_first(schema) is not None:
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
        held_values = {key: self.walk(value) for key, value in _schemas_in(schema)}
        if all(held is schema[key] for key, held in held_values.items()):
            return schema
        return _own_metadata({**schema, **held_values})

    def _reference(self, schema: dict[str, Any]) -> dict[str, Any]:
        ref = schema["schema_ref"]
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
                cls = _judged_first(held)
                if cls is not None:
                    self.judged_first[self.refs[ref]] = cls
                self.definitions.append({**held, "ref": self.refs[ref]})
        held_ref = self.refs[ref]
        return schema if held_ref == ref else {**schema, "schema_ref": held_ref}

    def _union(self, schema: dict[str, Any]) -> dict[str, Any]:
        metadata = schema.get("metadata")
        deferred = isinstance(metadata, dict) and _DEFERRED_DISCRIMINATOR in metadata
        choices: list[Any] = []
        changed = False
        for choice in schema["choices"]:
            member, label = choice if isinstance(choice, tuple) else (choice, None)
            held = self.walk(member)
            if held is not member:
                changed = True
                label = label or self._label(member)
                if deferred and held.get("schema_ref") in self.judged_first:
                    raise self._untaggable(self.judged_first[held["schema_ref"]])
            choices.append((held, label) if label else held)
        return _own_metadata({**schema, "choices": choices}) if changed else schema

    def _label(self, member: Any) -> str | None:
        """The name a union gives *member* in an error's location, as Pydantic names it.

        Pydantic names a member by the validator it builds for it, so the member is built on its
        own, as Pydantic built it, with every definition it refers to.
        """
        member = _unheld(member)
        try:
            definitions = self._definitions_of(member)
            if member.get("type") == "definition-ref":
                member = definitions[member["schema_ref"]]
            standalone = core_schema.definitions_schema(
                member, [{**target, "ref": ref} for ref, target in definitions.items()]
            )
            return SchemaValidator(standalone).title
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

    def _nested(self, schema: dict[str, Any]) -> dict[str, Any]:
        cls = schema.get("cls")
        if cls is self.owner or not _is_complete(cls):
            return self._node(schema)  # pydantic-core validates it by the schema it is handed
        if isinstance(cls, self.judged):
            return schema  # a complete BaseSchema: the validator it brings is held already
        held = self._node(schema)
        if held is schema:
            return schema
        # pydantic-core validates this node with the class's own validator, whatever schema it is
        # handed, and that validator does not judge: what it is given is judged first.
        return cast(
            "dict[str, Any]",
            core_schema.chain_schema(
                [
                    core_schema.no_info_wrap_validator_function(
                        _JudgedFirst(cast("type", cls)), cast("CoreSchema", _stand_in(held))
                    ),
                    cast("CoreSchema", {key: value for key, value in schema.items() if key != "ref"}),
                ]
            ),
        )

    def _untaggable(self, cls: type) -> TypeError:
        return TypeError(
            f"{self.owner.__name__} has {cls.__qualname__} as a choice of a discriminated union "
            "that refers back to a schema still being defined; Pydantic picks such a choice by "
            f"its tag only from the choice's own fields, and {cls.__qualname__} brings its own "
            "Pydantic validator, which reads a timestamp in it without judging its UTC offset "
            f"(ADR 0206); derive {cls.__qualname__} from BaseSchema"
        )


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
