"""Which column types a statistic can aggregate and group by, judged when it is declared (ADR 0204).

A declaration the database cannot answer fails on every request, and a 500 is the worst place to
find that out. PostgreSQL has no sum of text or of a boolean, no maximum of a UUID, a boolean or
a JSON value, and cannot key a group by JSON; SQLite answers a sum of text with ``0.0``, which is
worse. So a declaration is judged on its column's type when the class is defined. A type that
names no Python type is left to the database.
"""

from __future__ import annotations

import datetime as dt
import enum
import uuid
from collections.abc import Sequence
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy.types import JSON

if TYPE_CHECKING:
    from terp.core.aggregation import Dimension, Measure

#: The ops whose answer is derived from the values themselves. Over a group of one, each of
#: them is that one row's value, so none may run over a field declared personal, and each
#: takes only the types below.
VALUE_OPS: frozenset[str] = frozenset({"sum", "avg", "min", "max"})
#: What ``sum`` and ``avg`` add up: numbers. A boolean is an ``int`` to Python, and not here.
_SUMMABLE: tuple[type, ...] = (int, float, Decimal)
#: What ``min`` and ``max`` order.
_ORDERABLE: tuple[type, ...] = (int, float, Decimal, str, dt.date, dt.time, dt.timedelta)
#: What a group is keyed by, and a dimension's value carried back as.
_GROUPABLE: tuple[type, ...] = (str, int, float, bool, Decimal, dt.date, dt.time, uuid.UUID, enum.Enum)


def value_type(expression: Any) -> type | None:
    """The Python type *expression*'s values have, or ``None`` where its SQL type names none.

    A ``TypeDecorator`` that names none of its own (SQLModel's ``AutoString``) is read through
    to the type it stores as. SQLAlchemy 2.1 answers ``object`` for a type that names none,
    where earlier releases raised, and for JSON too, whose values are documents.
    """
    sql_type = getattr(expression, "type", None)
    while sql_type is not None:
        if isinstance(sql_type, JSON):
            return dict
        try:
            kind = sql_type.python_type
        except NotImplementedError:
            kind = object
        if kind is not object:
            return kind if isinstance(kind, type) else None
        sql_type = getattr(sql_type, "impl_instance", None)
    return None


def type_refusal(measures: Sequence[Measure], dimensions: Sequence[Dimension], owner: str) -> str:
    """Why a declaration would fail on every request because of its column's type, or ``""``."""
    for dimension in dimensions:
        kind = value_type(dimension.column)
        if kind is not None and not issubclass(kind, _GROUPABLE):
            return (
                f"{owner} groups by {dimension.name!r}, a {kind.__name__} column, and a group "
                "cannot be keyed by one: group by a column of text, a number, a date or an id."
            )
    for measure in measures:
        if measure.op not in VALUE_OPS or measure.column is None:
            continue
        kind = value_type(measure.column)
        adds = measure.op in ("sum", "avg")
        allowed = _SUMMABLE if adds else _ORDERABLE
        if kind is not None and (issubclass(kind, bool) or not issubclass(kind, allowed)):
            what = "adds up numbers" if adds else "orders numbers, text and times"
            return (
                f"{owner} declares {measure.name!r} as {measure.op} over a {kind.__name__} column, "
                f"and {measure.op} {what} only: count it, or count its distinct values."
            )
    return ""


__all__ = ["VALUE_OPS", "type_refusal", "value_type"]
