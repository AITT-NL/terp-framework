"""Personal data, declared per field: ``Personal`` and the readers that honour it (ADR 0190).

A field that holds personal data -- an email address, a phone number, a date of birth, a
person's name -- looks exactly like every other ``str`` or ``date`` column, so nothing
downstream could tell it apart. The log redacted secrets, because a secret has a shape or a
name a pattern can find; an address has neither. So the declaration is the model's:

    class Customer(BaseTable, table=True):
        email: str = Personal(max_length=320, index=True, unique=True)

:func:`Personal` is :func:`sqlmodel.Field` with one more fact recorded, in two places that
are each read by something:

* **the field's metadata**, which pydantic carries into every subclass and which
  :func:`personal_fields` reads from any model class, table or schema. A schema that
  redeclares the field without ``Personal`` has redeclared it as not personal, which is why
  the ``personal_fields_are_declared`` rule reads each declaration on its own.
* **the column's ``info``**, for a table model, so a reader that holds only the database
  metadata -- a copy that anonymises a database, say -- finds it without the model class
  (:func:`personal_columns`). Like ``Ref``'s declaration it changes no DDL, so adopting it
  costs no migration.

What reads it:

* **the log** -- a model rendered anywhere (``%s``, an f-string, an exception's text, a
  traceback) shows ``[PERSONAL]`` in place of each declared field, and a value logged
  under a declared field's name in ``extra=`` or ``log_context`` is replaced the same way
  (:func:`personal_field_names`); a database's refusal to store a row loses the row's
  declared values before it reaches ``log_context`` (:func:`withhold_personal_values`);
* **the audit trail** -- a payload keeps each declared field's key and loses its value
  (:func:`redact_personal`, which :class:`~terp.core.AuditPolicy` applies centrally);
* **events** -- a ``PUBLIC`` event or job may not declare a personal field in its payload,
  and :func:`redact_personal` is the copy of a payload that may leave the process;
* **validation errors** -- a Terp model that declares a personal field hides its input
  in a validation error's text, the one place the raw value reaches an exception without
  going through the model.

What it cannot see is a value that has already stopped being a field: ``f"{customer.email}"``
is a string, and so is ``customer.email`` passed on its own. Log the model or its id.
"""

from __future__ import annotations

import weakref
from collections.abc import Iterable, Mapping
from threading import Lock
from typing import Any, Final

from pydantic import BaseModel
from pydantic_core import PydanticUndefined
from sqlalchemy import MetaData
from sqlmodel import Field, SQLModel

#: What a declared personal field's value is replaced with, wherever it is withheld.
PERSONAL: Final[str] = "[PERSONAL]"

#: The key a ``Personal`` column carries in its SQLAlchemy ``Column.info``.
_COLUMN_INFO_KEY: Final[str] = "terp_personal"


class _PersonalMarker:
    """The fact :func:`Personal` appends to a field's metadata.

    Pydantic keeps metadata it does not recognise, untouched, on the field and on every
    subclass's copy of it; it neither validates against it nor puts it in a JSON schema,
    so the declaration changes no contract a client sees.
    """

    __slots__ = ()

    def __repr__(self) -> str:
        return "Personal"


_MARKER: Final[_PersonalMarker] = _PersonalMarker()


def Personal(default: Any = PydanticUndefined, **field_kwargs: Any) -> Any:  # noqa: N802 - a Field-style factory
    """Declare a model field as personal data; otherwise exactly :func:`sqlmodel.Field`.

    Use it wherever the field is declared, on the table and on each schema::

        class Customer(BaseTable, table=True):
            email: str = Personal(max_length=320, index=True, unique=True)

        class CustomerRead(BaseSchema):
            email: str = Personal()

    Every keyword is forwarded to :func:`sqlmodel.Field` unchanged. A hand-built
    ``sa_column=`` is marked in place.
    """
    kwargs = dict(field_kwargs)
    column = kwargs.get("sa_column")
    if column is not None:
        column.info[_COLUMN_INFO_KEY] = True
    else:
        column_kwargs = dict(kwargs.pop("sa_column_kwargs", None) or {})
        column_kwargs["info"] = {**column_kwargs.get("info", {}), _COLUMN_INFO_KEY: True}
        kwargs["sa_column_kwargs"] = column_kwargs
    info = Field(default, **kwargs)
    info.metadata.append(_MARKER)
    return info


# A model class's declared personal fields, computed once per class. Weak, so a class a test
# builds and drops does not outlive it here.
_fields_by_class: weakref.WeakKeyDictionary[type, frozenset[str]] = weakref.WeakKeyDictionary()


def personal_fields(model: type[BaseModel] | BaseModel) -> frozenset[str]:
    """The names of the fields *model* (a model class or instance) declares personal."""
    cls = model if isinstance(model, type) else type(model)
    names = _fields_by_class.get(cls)
    if names is None:
        fields = cls.model_fields if issubclass(cls, BaseModel) else {}
        names = frozenset(
            name
            for name, info in fields.items()
            if any(isinstance(item, _PersonalMarker) for item in info.metadata)
        )
        _fields_by_class[cls] = names
    return names


# Every field name some Terp model has declared personal, lower-cased: what lets the log and
# the audit trail recognise a value handed over under that name, with no model in sight.
_names: frozenset[str] = frozenset()
_names_lock = Lock()


def personal_field_names() -> frozenset[str]:
    """Every field name a model built on a Terp base class declares personal, lower-cased.

    The log redacts a value under any of these names in ``extra=`` or ``log_context``, and
    the audit trail in a payload, because a mapping carries no model to ask. It grows as
    model classes are defined; a model that inherits none of ``BaseTable``, ``BaseSchema``
    and ``BaseUpdateSchema`` is still masked when it is rendered, but its names are not
    collected here.
    """
    return _names


def is_personal_name(key: str) -> bool:
    """Whether *key* is the name of a field some Terp model declares personal."""
    return key.lower() in _names


def declare_model(cls: type[BaseModel]) -> None:
    """Record what the new model class *cls* declares (the Terp base classes call this).

    Its personal field names join :func:`personal_field_names`, and a model that declares
    any hides its input in a validation error's text: pydantic otherwise repeats the
    refused value (``input_value='...'``), and a refusal raised inside a service ends up
    in a traceback. The 422 a request body gets is unaffected -- its detail is built from
    the error's structured form, which keeps the input for the caller who sent it.
    """
    names = personal_fields(cls)
    if not names:
        return
    global _names
    with _names_lock:
        _names = _names | {name.lower() for name in names}
    if cls.model_config.get("hide_input_in_errors") is not True:
        cls.model_config["hide_input_in_errors"] = True
        # A forward reference still unresolved here is resolved on first use, as pydantic
        # always does, and then with the configuration above.
        cls.model_rebuild(force=True, raise_errors=False)


class _Withheld:
    """What a withheld value renders as inside a model's repr: ``[PERSONAL]``, unquoted."""

    __slots__ = ()

    def __repr__(self) -> str:
        return PERSONAL


WITHHELD: Final[_Withheld] = _Withheld()


def masked(value: Any) -> Any:
    """*value* as it may be rendered: models masked, at any depth, and nothing else changed.

    A model becomes a :class:`MaskedModel`; a list, tuple or dict is rebuilt around its
    masked items, and a dict's value under a declared personal name is withheld. Only the
    rendering differs: this is for ``repr`` and ``str``, never for data.
    """
    if isinstance(value, BaseModel):
        return MaskedModel(value)
    if isinstance(value, dict):
        return {
            key: WITHHELD if isinstance(key, str) and is_personal_name(key) else masked(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [masked(item) for item in value]
    if isinstance(value, tuple):
        return tuple(masked(item) for item in value)
    return value


def mask_repr_args(
    model: BaseModel, args: Iterable[tuple[str | None, Any]]
) -> list[tuple[str | None, Any]]:
    """Pydantic's ``__repr_args__`` for *model*, each declared personal field withheld."""
    personal = personal_fields(model)
    return [
        (name, WITHHELD if name in personal else masked(value)) for name, value in args
    ]


class MaskedModel:
    """A model as it may be rendered: pydantic's own ``repr`` and ``str``, fields withheld.

    The Terp base classes mask themselves; this does the same for any other pydantic
    model, which is how the log renders a plain ``SQLModel`` it was handed.
    """

    __slots__ = ("_model",)

    def __init__(self, model: BaseModel) -> None:
        self._model = model

    def _render(self, separator: str) -> str:
        args = mask_repr_args(self._model, self._model.__repr_args__())
        return separator.join(
            repr(value) if name is None else f"{name}={value!r}" for name, value in args
        )

    def __repr__(self) -> str:
        return f"{self._model.__repr_name__()}({self._render(', ')})"

    def __str__(self) -> str:
        return self._render(" ")


def redact_personal(value: Any, *, model: type[BaseModel] | None = None) -> Any:
    """A copy of *value* that holds no declared personal value, every key kept.

    The shared reader for anything that writes a model's data where it is kept or sent:
    the audit trail's payload, and an event payload that leaves the process.

    * A **model** becomes its JSON-mode dump with each declared personal field
      :data:`PERSONAL`, nested models redacted the same way.
    * A **mapping** keeps its keys; the value under a declared personal name is replaced,
      where the names are :func:`personal_field_names` plus *model*'s own (pass the
      payload's schema when the mapping is its dump, so a plain model's fields count).
    * A list or tuple is redacted item by item; anything else is returned as it is.
    """
    if isinstance(value, BaseModel):
        return _redact_model(value)
    if isinstance(value, Mapping):
        own = personal_fields(model) if model is not None else frozenset()
        return {
            key: (
                PERSONAL
                if isinstance(key, str) and (key in own or is_personal_name(key))
                else redact_personal(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_personal(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_personal(item) for item in value)
    return value


def _redact_model(instance: BaseModel) -> dict[str, Any]:
    """*instance*'s JSON-mode dump with its own and its nested models' personal fields withheld."""
    personal = personal_fields(instance)
    dumped = instance.model_dump(mode="json")
    for name in dumped:
        if name in personal:
            dumped[name] = PERSONAL
            continue
        current = getattr(instance, name, None)
        if isinstance(current, BaseModel):
            dumped[name] = _redact_model(current)
        elif isinstance(current, (list, tuple)) and current and all(
            isinstance(item, BaseModel) for item in current
        ):
            dumped[name] = [_redact_model(item) for item in current]
        else:
            dumped[name] = redact_personal(dumped[name])
    return dumped


def withhold_personal_values(text: str, instance: BaseModel) -> str:
    """*text* with every declared personal value *instance* holds replaced by ``[PERSONAL]``.

    For text the framework builds from a row it has in hand, such as a database's refusal
    to store it (``Key (email)=(...) already exists``): the values are known, so they are
    what is removed, longest first so a value inside another goes with it.
    """
    values = sorted(
        {
            str(current)
            for name in personal_fields(instance)
            if (current := getattr(instance, name, None)) is not None and str(current)
        },
        key=len,
        reverse=True,
    )
    for current in values:
        text = text.replace(current, PERSONAL)
    return text


def personal_columns(metadata: MetaData | None = None) -> dict[str, tuple[str, ...]]:
    """Every table's ``Personal`` columns, read from database metadata alone.

    *metadata* defaults to the shared ``SQLModel.metadata``. Tables without a personal
    column are left out, so the result is exactly what a database copy must anonymise.
    """
    source = metadata if metadata is not None else SQLModel.metadata
    found: dict[str, tuple[str, ...]] = {}
    for table in source.sorted_tables:
        columns = tuple(
            column.name for column in table.columns if column.info.get(_COLUMN_INFO_KEY) is True
        )
        if columns:
            found[table.fullname] = columns
    return found


def refuse_public_personal_payload(kind: str, name: str, schema: type) -> None:
    """Refuse a ``PUBLIC`` event or job whose payload schema declares a personal field.

    ``PUBLIC`` says the payload is safe to surface outward; a declared personal field says
    it is not. The two cannot both be true, so the definition is refused where it is made.
    """
    declared = personal_fields(schema)
    if declared:
        raise ValueError(
            f"{kind} {name!r} is PUBLIC, but its payload schema {schema.__name__} declares "
            f"personal fields {sorted(declared)}: a public payload is one that may be "
            "surfaced outward. Declare it INTERNAL or RESTRICTED, or carry an id instead"
        )


__all__ = [
    "MaskedModel",
    "PERSONAL",
    "Personal",
    "declare_model",
    "is_personal_name",
    "mask_repr_args",
    "masked",
    "personal_columns",
    "personal_field_names",
    "personal_fields",
    "redact_personal",
    "refuse_public_personal_payload",
    "withhold_personal_values",
]
