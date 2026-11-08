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
from terp.core.filtering import local_midnight

if TYPE_CHECKING:
    from terp.core.aggregation import TimeStep, Window


def _next_step(day: dt.date, step: TimeStep) -> dt.date:
    if step == "day":
        return day + dt.timedelta(days=1)
    if step == "week":
        return day + dt.timedelta(days=7 - day.weekday())
    return (day.replace(day=1) + dt.timedelta(days=32)).replace(day=1)


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


#: The most terms SQLite reads in one compound ``SELECT``: a longer series is joined in groups.
_COMPOUND_TERMS = 500


def window_days(window: Window) -> list[dt.date]:
    """The calendar dates that open the window's steps, and the day after its end, in order.

    Each step is labelled by the date that opens it, never by its start read back in the zone:
    a day the zone skipped entirely (Samoa's 30 December 2011) has no instant of its own, and
    its start is the next day's.
    """
    if window.end < window.start:
        raise ValidationFailedError("A window's end is on or after its start.")
    last = window.end + dt.timedelta(days=1)
    if window.step is None:
        return [window.start, last]
    days = [window.start]
    while days[-1] < last:
        days.append(min(_next_step(days[-1], window.step), last))
    return days


def window_bounds(window: Window, zone: ZoneInfo) -> list[dt.datetime]:
    """The UTC instants that cut the window into its steps; the whole window without one."""
    return [local_midnight(day, zone) for day in window_days(window)]


def _steps_table(bounds: Sequence[dt.datetime], column_type: Any) -> Any:
    """The window's steps as rows ``(i, lo, hi)``, to join a row to the step it falls in.

    A join to a small table of bound instants groups by a plain column and is the cheapest
    form measured on both dialects (a few times faster than a balanced ``CASE``, an order of
    magnitude faster than one ``WHEN`` per step). Each bound is bound with the bucket column's
    own type, so it is stored-form compatible on SQLite and a ``timestamptz`` on PostgreSQL.
    SQLite reads at most 500 terms in one compound ``SELECT``, so a longer series is joined in
    groups of that many, each group one term of the next.
    """
    terms: list[Any] = [
        sa_select(
            literal(index, Integer).label("i"),
            literal(bounds[index], column_type).label("lo"),
            literal(bounds[index + 1], column_type).label("hi"),
        )
        for index in range(len(bounds) - 1)
    ]
    while len(terms) > _COMPOUND_TERMS:
        terms = [
            union_all(*terms[at : at + _COMPOUND_TERMS]).subquery().select()
            for at in range(0, len(terms), _COMPOUND_TERMS)
        ]
    return (union_all(*terms) if len(terms) > 1 else terms[0]).subquery("steps")


__all__ = ["window_bounds", "window_days", "window_steps"]
