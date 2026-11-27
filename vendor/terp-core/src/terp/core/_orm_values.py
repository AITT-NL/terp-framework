"""Mapped JSON columns and the value comparisons used when saving ORM rows."""

from copy import deepcopy
from enum import Enum
from typing import Any

from sqlalchemy import JSON, inspect
from sqlalchemy.orm import InstanceState
from sqlalchemy.orm.attributes import NO_VALUE, flag_modified


_JSON_COLUMN_FIELDS: dict[type, frozenset[str]] = {}


def _json_column_fields(model: type) -> frozenset[str]:
    """Names of *model*'s columns whose database type is JSON (incl. Postgres JSONB).

    The write chokepoint knows the column types, so it can dump exactly those fields
    in pydantic's ``json`` mode instead of leaving every module to discover — from a
    ``TypeError: Object of type UUID is not JSON serializable`` raised deep inside
    ``flush`` — that a typed value object needs a ``PlainSerializer`` annotation.
    """
    cached = _JSON_COLUMN_FIELDS.get(model)
    if cached is not None:
        return cached
    fields = frozenset(
        column.key
        for column in inspect(model).columns
        if isinstance(column.type, JSON)
    )
    _JSON_COLUMN_FIELDS[model] = fields
    return fields


def _snapshot(value: Any) -> Any:
    # A binary column can hold a buffer. Copy the bytes without trying to pickle the view.
    if isinstance(value, (memoryview, bytearray)):
        return bytes(value)
    if isinstance(value, (dict, list, set)):
        return deepcopy(value)
    return value


class _JsonBoolean(Enum):
    FALSE = False
    TRUE = True


def _json_snapshot(value: Any) -> Any:
    # JSON booleans and numbers are distinct even though Python's True equals 1.
    if isinstance(value, bool):
        return _JsonBoolean(value)
    if isinstance(value, dict):
        return {key: _json_snapshot(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_snapshot(item) for item in value]
    return _snapshot(value)


def _preserve_json_types(state: InstanceState) -> None:
    # SQLAlchemy normally skips equal assignments. A JSON boolean and a number
    # can compare equal in Python while persisting different documents.
    for key in _json_column_fields(state.class_) & state.committed_state.keys():
        old = state.committed_state[key]
        new = state.dict.get(key, NO_VALUE)
        if old == new and _json_snapshot(old) != _json_snapshot(new):
            flag_modified(state.object, key)
