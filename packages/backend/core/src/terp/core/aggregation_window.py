"""A statistic's window in calendar steps of a zone: how many, and where each one starts (ADR 0204).

The caps of a series are judged on the count of its steps, which is counted without building
them, so a window of every day from year 1 to 9999 is refused before a single bound exists.
The bounds are local midnights read as UTC instants, so a day the clocks change keeps its length.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from sqlalchemy import Integer, literal, union_all
from sqlalchemy import select as sa_select

from terp.core.errors import ValidationFailedError

if TYPE_CHECKING:
    from terp.core.aggregation import TimeStep, Window


def _next_step(day: dt.date, step: TimeStep) -> dt.date:
    if step == "day":
        return day + dt.timedelta(days=1)
    if step == "week":
        return day + dt.timedelta(days=7 - day.weekday())
    return (day.replace(day=1) + dt.timedelta(days=32)).replace(day=1)


def _midnight(day: dt.date, zone: ZoneInfo) -> dt.datetime:
    """Local midnight of *day* in *zone*, as a UTC instant (a short day keeps its length)."""
    return dt.datetime.combine(day, dt.time(), tzinfo=zone).astimezone(dt.UTC)


def window_steps(window: Window) -> int:
    """How many steps *window* holds, counted without building them; one without a step.

    The caps are judged on this, so a window of every day from year 1 to 9999 is refused
    before a single bound is built.
    """
    if window.end < window.start:
        raise ValidationFailedError("A window's end is on or after its start.")
    start, last = window.start, window.end + dt.timedelta(days=1)
    if window.step is None:
        return 1
    if window.step == "day":
        return (last - start).days
    if window.step == "week":
        monday = start + dt.timedelta(days=7 - start.weekday())  # where the first step ends
        return 1 if monday >= last else 1 + -(-(last - monday).days // 7)
    months = (last.year - start.year) * 12 + last.month - start.month
    return months + (1 if last.day > 1 else 0)


def window_bounds(window: Window, zone: ZoneInfo) -> list[dt.datetime]:
    """The UTC instants that cut the window into its steps; the whole window without one."""
    if window.end < window.start:
        raise ValidationFailedError("A window's end is on or after its start.")
    last = window.end + dt.timedelta(days=1)
    if window.step is None:
        return [_midnight(window.start, zone), _midnight(last, zone)]
    days = [window.start]
    while days[-1] < last:
        days.append(min(_next_step(days[-1], window.step), last))
    return [_midnight(day, zone) for day in days]


def _steps_table(bounds: Sequence[dt.datetime], column_type: Any) -> Any:
    """The window's steps as rows ``(i, lo, hi)``, to join a row to the step it falls in.

    A join to a small table of bound instants groups by a plain column and is the cheapest
    form measured on both dialects (a few times faster than a balanced ``CASE``, an order of
    magnitude faster than one ``WHEN`` per step). Each bound is bound with the bucket column's
    own type, so it is stored-form compatible on SQLite and a ``timestamptz`` on PostgreSQL.
    """
    rows = [
        sa_select(
            literal(index, Integer).label("i"),
            literal(bounds[index], column_type).label("lo"),
            literal(bounds[index + 1], column_type).label("hi"),
        )
        for index in range(len(bounds) - 1)
    ]
    return (union_all(*rows) if len(rows) > 1 else rows[0]).subquery("steps")


__all__ = ["window_bounds", "window_steps"]
