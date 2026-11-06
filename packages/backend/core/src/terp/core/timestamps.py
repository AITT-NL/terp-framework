"""A timestamp a client sends carries its UTC offset (ADR 0206).

A value with no offset names no instant: ``2026-11-06T10:00:00`` is ten in the morning in
whichever zone its sender meant. Stored as UTC, which is what ``UtcDateTime`` does with a
naive value, it puts a sender one zone east of UTC an hour off, and nothing says so. The
published contract already rules such a value out: a ``datetime`` field is published as
``format: date-time``, RFC 3339's production, whose offset is not optional. So the request
boundary holds a client to the contract it was given.

Two doors carry a client's timestamp in, and both refuse one without an offset:

* a request body: a ``BaseSchema`` field typed ``datetime`` (or ``datetime | None``, or a list
  of them) refuses text that reads as a date and time with no offset, as a 422 at the field;
* a declared filter (:mod:`terp.core.filtering`): a bound with no offset is a 400 that names
  the filter.

Only a client's text is judged. A ``datetime`` object reaching a schema was built by the
server, read back from a row or computed in code, and a number is a Unix time, which is UTC.
So a response model built from rows validates exactly as before.

The one way around it is :data:`NaiveMeansUtc`, a type that reads a value with no offset as
UTC, for a sender known to send UTC without saying so. The
``request_timestamps_carry_their_offset`` rule refuses each use of it unless the line carries
the rule's marker, which the app's escape-hatch budget counts, so taking it is a decision a
reviewer sees.
"""

from __future__ import annotations

import types
import weakref
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Annotated, Any, Union, get_args, get_origin

from pydantic import AfterValidator, TypeAdapter, ValidationError
from pydantic_core import InitErrorDetails, PydanticCustomError

from terp.core.errors import ValidationFailedError

#: What a refusal tells the sender, in a body and in a filter alike.
OFFSET_REQUIRED = (
    "A date and time needs its UTC offset, for example 2026-11-06T10:00:00Z or "
    "2026-11-06T11:00:00+01:00"
)


class _ReadsNaiveAsUtc:
    """The mark :data:`NaiveMeansUtc` carries, which the body refusal steps aside for."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "NaiveMeansUtc"


_READS_NAIVE_AS_UTC = _ReadsNaiveAsUtc()


def _as_utc_when_naive(value: datetime) -> datetime:
    return value if value.utcoffset() is not None else value.replace(tzinfo=UTC)


NaiveMeansUtc = Annotated[datetime, AfterValidator(_as_utc_when_naive), _READS_NAIVE_AS_UTC]
"""A timestamp that reads a value with no offset as UTC: the escape from ADR 0206.

Declare it on a field or a query parameter whose sender is known to send UTC without an
offset. The value arrives aware, in UTC, so a declared filter takes it too. Every use is
refused by the ``request_timestamps_carry_their_offset`` rule unless its line carries
``# arch-allow-request-timestamps-carry-their-offset: <reason>``.
"""

_SEQUENCES = (list, tuple, set, frozenset)

#: ``(input keys, shape)`` per schema class, for the fields the body refusal judges.
_FIELDS: weakref.WeakKeyDictionary[type, tuple[tuple[tuple[str, ...], str], ...]] = (
    weakref.WeakKeyDictionary()
)

_DATETIME: TypeAdapter[datetime] = TypeAdapter(datetime)


def _shape(annotation: Any) -> str | None:
    """``"one"`` or ``"many"`` for a timestamp field the refusal judges, else ``None``."""
    origin = get_origin(annotation)
    if origin is Annotated:
        base, *metadata = get_args(annotation)
        if any(item is _READS_NAIVE_AS_UTC for item in metadata):
            return None
        return _shape(base)
    if annotation is datetime:
        return "one"
    if origin is Union or origin is types.UnionType:
        shapes = {_shape(arg) for arg in get_args(annotation) if arg is not type(None)}
        return shapes.pop() if len(shapes) == 1 else None
    if origin in _SEQUENCES:
        items = [arg for arg in get_args(annotation) if arg is not Ellipsis]
        if items and all(_shape(item) == "one" for item in items):
            return "many"
    return None


def _timestamp_fields(model: type) -> tuple[tuple[tuple[str, ...], str], ...]:
    known = _FIELDS.get(model)
    if known is None:
        found = []
        for name, info in model.model_fields.items():  # type: ignore[attr-defined]
            if any(item is _READS_NAIVE_AS_UTC for item in info.metadata):
                continue
            shape = _shape(info.annotation)
            if shape is None:
                continue
            keys = {name}
            for alias in (info.alias, info.validation_alias):
                if isinstance(alias, str):
                    keys.add(alias)
            found.append((tuple(sorted(keys)), shape))
        known = tuple(found)
        _FIELDS[model] = known
    return known


def _names_no_instant(value: object) -> bool:
    """Whether *value* is text that reads as a date and time with no offset."""
    if not isinstance(value, str):
        return False
    try:
        parsed = _DATETIME.validate_python(value)
    except ValidationError:
        return False  # not a timestamp at all: the field's own validation says so
    return parsed.utcoffset() is None


def _refusal(loc: tuple[str | int, ...], value: object) -> InitErrorDetails:
    return InitErrorDetails(
        type=PydanticCustomError("timestamp_offset_required", OFFSET_REQUIRED),
        loc=loc,
        input=value,
    )


def refuse_timestamps_without_an_offset(model: type, data: object) -> None:
    """Refuse a client's timestamp text that carries no UTC offset (ADR 0206).

    *data* is what *model* is about to validate. Only a mapping is a client's body: an object,
    a row or a model, was built by the server and passes. Every such field is refused at once,
    each as its own error located at the field.
    """
    if not isinstance(data, Mapping):
        return
    errors: list[InitErrorDetails] = []
    for keys, shape in _timestamp_fields(model):
        for key in keys:
            if key not in data:
                continue
            value = data[key]
            if shape == "one":
                if _names_no_instant(value):
                    errors.append(_refusal((key,), value))
            elif isinstance(value, list | tuple):
                errors.extend(
                    _refusal((key, index), item)
                    for index, item in enumerate(value)
                    if _names_no_instant(item)
                )
            break
    if errors:
        raise ValidationError.from_exception_data(model.__name__, errors)


def require_offset(name: str, value: datetime) -> None:
    """Refuse a declared filter's bound that carries no UTC offset, naming the filter."""
    if value.utcoffset() is None:
        raise ValidationFailedError(
            f"Filter {name!r} needs a date and time with its UTC offset, for example "
            "2026-11-06T10:00:00Z."
        )


__all__ = ["OFFSET_REQUIRED", "NaiveMeansUtc", "refuse_timestamps_without_an_offset", "require_offset"]
