"""Which fields declared personal a SQL expression reads (ADR 0204 decision 5).

A statistic never answers for one person's personal data, so a dimension, a time bucket, a
value-derived measure, and a filter that narrows a statistic, are refused when they read a
field declared personal. The attribute a declaration names is not the only way to read one:
under a function, a cast, a label, an alias, the model's Core table or a subquery's column it
is the same field. So an expression is walked down to the columns it stands for, and each is
matched to the models that map it.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Column, Table
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.sql import visitors
from sqlalchemy.sql.elements import ColumnClause, TextClause

from terp.core.personal import personal_fields
from terp.core.scoping import _models_of


def _fields_on(column: Column, table: Table) -> set[str]:
    """The personal fields a model maps onto *column* of *table*, as ``Model.field``.

    Matched by the table's and the column's names, case folded: a copy of the Table, or a
    Core alias of it, reads the same field.
    """
    found: set[str] = set()
    for model in _models_of(table):
        mapper = sa_inspect(model)
        for key in personal_fields(model):
            columns = getattr(mapper.get_property(key), "columns", ())
            if any(own.name.casefold() == column.name.casefold() for own in columns):
                found.add(f"{model.__name__}.{key}")
    return found


def personal_reads(expression: Any) -> str:
    """Why *expression* may not shape a statistic, as a phrase, or ``""``.

    It reads a field declared personal wherever it holds one: under a function, a cast, a
    label, an alias, the model's Core table, or a subquery's column, each read back to the
    columns it stands for. SQL that names no model column, literal SQL or a bare column name,
    could be any field, so it counts too, since nothing can tell it apart from a personal one.
    """
    fields: set[str] = set()
    unnamed = False
    element_of = getattr(expression, "__clause_element__", None)
    pending = [element_of() if callable(element_of) else expression]
    followed: set[int] = set()
    while pending:
        for element in visitors.iterate(pending.pop()):
            if isinstance(element, TextClause):
                unnamed = True
            elif isinstance(element, ColumnClause):
                for base in element.base_columns:
                    table = getattr(base, "table", None)
                    if isinstance(base, Column) and isinstance(table, Table):
                        fields |= _fields_on(base, table)
                    elif isinstance(base, ColumnClause):
                        unnamed = True  # a literal column, or a name the FROM resolves
                    elif id(base) not in followed:  # what a subquery's column computes
                        followed.add(id(base))
                        pending.append(base)
    if fields:
        return f"a field declared personal ({', '.join(sorted(fields))})"
    if unnamed:
        return "SQL that names no model column, which could be a field declared personal"
    return ""


__all__ = ["personal_reads"]
