"""The HTTP surface of declared statistics: the capped query, and the typed response (ADR 0204).

:mod:`terp.core.aggregation` computes a page of groups; this module is what a route needs around
it. :data:`StatisticsQueryDep` parses a statistics request with every list and string capped,
the way :data:`~terp.core.pagination.PaginationDep` caps a page, and :func:`group_model` builds
the response model one group has, typed by the declarations, so the API contract and the
generated client know each figure's name and type.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Query
from pydantic import BaseModel, ConfigDict, StringConstraints, create_model
from sqlalchemy.orm.attributes import InstrumentedAttribute

from terp.core.aggregation import DEFAULT_MAX_POINTS, Measure, Statistics, TimeStep, Window
from terp.core.errors import ValidationFailedError


def _python_type(column: InstrumentedAttribute) -> Any:
    try:
        return column.type.python_type
    except NotImplementedError:
        return Any


def _measure_type(measure: Measure) -> Any:
    if measure.op in ("count", "count_distinct"):
        return int
    if measure.op == "avg":
        return float
    return _python_type(measure.column)  # type: ignore[arg-type]


def group_model(statistics: Statistics, name: str) -> type[BaseModel]:
    """A response model for one group of *statistics*, typed by its declarations.

    :class:`AggregateGroup` is the value :func:`aggregate` returns, and its maps are untyped:
    in an OpenAPI document every service would share one shape of ``additionalProperties``.
    This is the same group as the client should see it, one field per declared dimension and
    measure, each typed by its column and its aggregate. A field the request did not ask for
    is ``null``. Name it after the service, since the document needs the names unique.
    """
    dimensions = create_model(  # type: ignore[call-overload]
        f"{name}Dimensions",
        **{d.name: (_python_type(d.column) | None, None) for d in statistics.dimensions},
    )
    measures = create_model(  # type: ignore[call-overload]
        f"{name}Measures", **{m.name: (_measure_type(m) | None, None) for m in statistics.measures}
    )
    point = create_model(  # type: ignore[call-overload]
        f"{name}Point", start=(dt.datetime, ...), date=(dt.date, ...), measures=(measures, ...)
    )
    return create_model(  # type: ignore[call-overload,no-any-return]
        f"{name}Group",
        __config__=ConfigDict(from_attributes=True),
        dimensions=(dimensions, ...),
        measures=(measures, ...),
        series=(list[point] | None, None),  # type: ignore[valid-type]
    )


_StatisticName = Annotated[str, StringConstraints(max_length=64, pattern=r"^[a-z][a-z0-9_]*$")]
_SortKey = Annotated[str, StringConstraints(max_length=65, pattern=r"^-?[a-z][a-z0-9_]*$")]


@dataclass(frozen=True)
class StatisticsQuery:
    """What a statistics route was asked, already capped: names, a window, a page."""

    measures: tuple[str, ...]
    by: tuple[str, ...] = ()
    sort: tuple[str, ...] | None = None
    window: Window | None = None
    skip: int = 0
    limit: int | None = None


def _statistics_query(
    measures: Annotated[list[_StatisticName], Query(min_length=1, max_length=16)],
    by: Annotated[list[_StatisticName] | None, Query(max_length=8)] = None,
    sort: Annotated[list[_SortKey] | None, Query(max_length=8)] = None,
    bucket: Annotated[_StatisticName | None, Query(description="The time bucket to window by.")] = None,
    start: Annotated[dt.date | None, Query(description="The window's first day, included.")] = None,
    end: Annotated[dt.date | None, Query(description="The window's last day, included.")] = None,
    zone: Annotated[str, Query(max_length=64, description="An IANA time zone.")] = "UTC",
    step: Annotated[TimeStep | None, Query(description="A series per day, week or month.")] = None,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int | None, Query(ge=1, le=DEFAULT_MAX_POINTS)] = None,
) -> StatisticsQuery:
    window = None
    if bucket is not None:
        if start is None or end is None:
            raise ValidationFailedError("A window names its first and its last day.")
        window = Window(bucket, start=start, end=end, zone=zone, step=step)
    elif start is not None or end is not None or step is not None:
        raise ValidationFailedError("A window names the time bucket it is on.")
    return StatisticsQuery(
        measures=tuple(measures),
        by=tuple(by or ()),
        sort=tuple(sort) if sort else None,
        window=window,
        skip=skip,
        limit=limit,
    )


StatisticsQueryDep = Annotated[StatisticsQuery, Depends(_statistics_query)]
"""A statistics route's query, every list and string capped like :data:`PaginationDep`'s."""


__all__ = ["StatisticsQuery", "StatisticsQueryDep", "group_model"]
