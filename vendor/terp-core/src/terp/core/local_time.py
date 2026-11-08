"""The wall time of a named place, read as the instant it names (ADR 0207).

A timestamp sent without a UTC offset names no instant (ADR 0206), unless the receiver knows
the place whose wall time it is: ``2026-11-06T10:00`` in ``Europe/Amsterdam`` is
``2026-11-06T09:00:00Z``. :class:`LocalTimeIn` declares that place on a field or a query
parameter, so the field reads such a value as the instant it names, and a value with its
offset as the instant it already names.

The wall time names no instant where the clocks skip it, and two where they repeat it, so both
are refused, each saying what to send instead. A zone that names no place, such as UTC under
any of its names, is refused when declared: reading a time in UTC is the escape,
``NaiveMeansUtc``, which the ``request_timestamps_carry_their_offset`` rule counts. The
timestamp boundary in :mod:`terp.core.timestamps` leaves the type's node unjudged, knowing it by
the type's own reader.
"""

from __future__ import annotations

from datetime import UTC, datetime
from functools import cache
from importlib.resources import files
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import GetCoreSchemaHandler
from pydantic_core import CoreSchema, PydanticCustomError, core_schema

#: Instants across a zone's history, twice a year: enough to tell a place from a fixed offset,
#: and one zone from another.
_MOMENTS = tuple(datetime(year, month, 1, tzinfo=UTC) for year in range(1800, 2101, 25) for month in (1, 7))


def _keeps_one_offset(zone: ZoneInfo) -> bool:
    """Whether *zone* has kept one UTC offset through all of its history.

    UTC under any of its names (``UTC``, ``Etc/Zulu``, ``GMT``) and a fixed offset (``Etc/GMT-1``,
    ``EST``) have. A place has not: its local time began as its own mean solar time and has
    moved since, so it reads one offset in 1800 and another now, and most read two a year.
    """
    return len({moment.astimezone(zone).utcoffset() for moment in _MOMENTS}) == 1


@cache
def _pinned_keys() -> frozenset[str]:
    """Every key of the ``tzdata`` package ``terp-core`` pins: the same list on every host."""
    return frozenset(files("tzdata").joinpath("zones").read_text(encoding="utf-8").split())


def _names_a_place(zone: str) -> ZoneInfo | None:
    """The zone *zone* names, when it is a place's; ``None`` for UTC, a fixed offset or the host.

    A place is named Area/Location, as the IANA database files it, under an area other than
    ``Etc``, which holds UTC and the fixed offsets; and the name must be one the pinned ``tzdata``
    package holds. Both are judged on the name, the same on every host. The host's own database
    cannot judge it: the package's releases from 2024b read ``EST``, ``MST`` and ``HST`` as
    Panama, Phoenix and Honolulu, where many a host still reads fixed offsets, so an app passed
    its tests on one host and failed at import on another. A name without an area (``EST``,
    ``UTC``, ``Japan``, the host's ``localtime``) is refused everywhere; its place has a name of
    its own (``America/Panama``, ``Asia/Tokyo``).
    """
    area, _, location = zone.partition("/")
    if not location or area == "Etc" or zone not in _pinned_keys():
        return None
    place = ZoneInfo(zone)
    return None if _keeps_one_offset(place) else place


def _reads_its_place(marker: LocalTimeIn) -> bool:
    """Whether *marker* still reads in a place's zone, the one its name gives.

    The type refuses a change through its attributes, but ``object.__setattr__`` reaches past
    that. So the timestamp boundary asks this of each one it trusts: the zone the reader uses
    must give the offsets the named zone gives, at every moment sampled, and that zone must be
    a place's. Anything else, a zone swapped for UTC or a name swapped with it, is refused.
    """
    try:
        place = _names_a_place(object.__getattribute__(marker, "zone"))
        zone = object.__getattribute__(marker, "_zone")
        return place is not None and all(
            moment.astimezone(zone).utcoffset() == moment.astimezone(place).utcoffset() for moment in _MOMENTS
        )
    except (ZoneInfoNotFoundError, ValueError, TypeError, AttributeError):
        return False


def _reads_back(candidate: datetime, zone: ZoneInfo, local: datetime) -> bool:
    """Whether *candidate*, as an instant, reads in *zone* as the wall time *local*."""
    return candidate.astimezone(UTC).astimezone(zone).replace(tzinfo=None) == local


def _instant_in(local: datetime, zone: ZoneInfo, name: str) -> datetime:
    """The instant the wall time *local* names in *zone*, in UTC.

    Both readings of the wall time, before and after a change of the clocks, are tried, and
    each instant that reads back as the wall time counts. One is the instant; none means the
    clocks skip the wall time there, and two that they repeat it, so both are refused, each
    saying what to send instead.
    """
    readings = (local.replace(tzinfo=zone, fold=0), local.replace(tzinfo=zone, fold=1))
    instants = sorted({reading.astimezone(UTC) for reading in readings if _reads_back(reading, zone, local)})
    if len(instants) == 1:
        return instants[0]
    if instants:
        raise PydanticCustomError(
            "local_time_repeated",
            "{local} happens twice in {zone}, where the clocks repeat it; send it with its UTC "
            "offset, {earlier} or {later}",
            {
                "local": local.isoformat(),
                "zone": name,
                "earlier": instants[0].astimezone(zone).isoformat(),
                "later": instants[1].astimezone(zone).isoformat(),
            },
        )
    raise PydanticCustomError(
        "local_time_skipped",
        "{local} does not happen in {zone}, where the clocks skip it; send a time that "
        "happens there, or one with its UTC offset",
        {"local": local.isoformat(), "zone": name},
    )


class LocalTimeIn:
    """A timestamp sent as the wall time of a named zone: ``LocalTimeIn("Europe/Amsterdam")``.

    Declare it on a field or a query parameter whose sender sends the local time of a place
    the app knows, as ``Annotated[datetime, LocalTimeIn("Europe/Amsterdam")]`` (ADR 0207). The
    field's own ``datetime`` reads the value first, with the field's settings, strictness
    included. A value without a UTC offset is then read as a local time in the zone, and one
    with an offset is the instant it names, so the value arrives as an instant, aware and in
    UTC, and a declared filter takes it too. A wall time the clocks skip in the zone is
    refused, error type ``local_time_skipped``, and one they repeat, ``local_time_repeated``,
    whose message names both instants it could be.

    The zone names the instant, so this is no escape, and it is held to that. A key that names
    no place, which is UTC under any name, a fixed offset, an old abbreviation such as ``EST``,
    or the host's own setting, is refused when declared, judged by its name the same way on
    every host: reading a time in UTC is ``NaiveMeansUtc``'s, which the
    ``request_timestamps_carry_their_offset`` rule counts. The type cannot be subclassed and
    refuses a change through its attributes, since the timestamp boundary trusts its reader by
    its own function; it reads the zone again too, so one swapped behind the type's back with
    ``object.__setattr__`` before the app starts is refused. The published contract is the one a
    ``datetime`` has.
    """

    __slots__ = ("_zone", "zone")

    def __init__(self, zone: str) -> None:
        try:
            place = ZoneInfo(zone)
        except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
            raise ValueError(
                f"LocalTimeIn({zone!r}) names no time zone this server knows; name an IANA "
                "zone, for example 'Europe/Amsterdam'"
            ) from exc
        if _names_a_place(zone) is None:
            raise ValueError(
                f"LocalTimeIn({zone!r}) names no place's wall time, but UTC, a fixed offset, an "
                "old abbreviation or the host's own setting; name a place as Area/Location, the "
                "way the IANA database files it, for example 'Europe/Amsterdam' or "
                "'America/Panama'. A sender known to send UTC without saying so takes "
                "NaiveMeansUtc, which the request_timestamps_carry_their_offset rule counts"
            )
        object.__setattr__(self, "_zone", place)
        object.__setattr__(self, "zone", zone)

    def __init_subclass__(cls, **kwargs: object) -> None:
        raise TypeError(
            "LocalTimeIn cannot be subclassed: the timestamp boundary trusts its reader by its "
            "own function. Declare Annotated[datetime, LocalTimeIn('<zone>')], and read text of "
            "your own in a validator the request_timestamps_carry_their_offset rule counts"
        )

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError(f"{self!r} is fixed once declared; declare another LocalTimeIn")

    def __delattr__(self, name: str) -> None:
        raise AttributeError(f"{self!r} is fixed once declared; declare another LocalTimeIn")

    def __copy__(self) -> LocalTimeIn:
        return self

    def __deepcopy__(self, memo: dict[int, object]) -> LocalTimeIn:
        return self

    def __reduce__(self) -> tuple[type[LocalTimeIn], tuple[str]]:
        return (LocalTimeIn, (self.zone,))

    def __get_pydantic_core_schema__(
        self, source: Any, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        schema = handler(source)
        if schema.get("type") != "datetime" or "tz_constraint" in schema or "now_op" in schema:
            raise TypeError(
                f"LocalTimeIn({self.zone!r}) reads a plain datetime itself, so it goes directly "
                f"after one: Annotated[datetime, LocalTimeIn({self.zone!r})], with any other "
                "metadata after it, never an aware, naive, past or future datetime"
            )
        return core_schema.no_info_after_validator_function(self._read, schema)

    def _read(self, read: datetime) -> datetime:
        """The instant *read* names, in UTC: as it is with an offset, as a local time without.

        The field's own ``datetime`` has read the value already, with its settings, so whatever
        it refuses is refused as a plain timestamp field would refuse it. An instant outside the
        years a timestamp holds once read as UTC is refused rather than left to overflow.
        """
        try:
            if read.utcoffset() is not None:
                return read.astimezone(UTC)
            return _instant_in(read, self._zone, self.zone)
        except OverflowError as exc:
            raise PydanticCustomError(
                "timestamp_out_of_range",
                "{value} falls outside the years 1 to 9999 once read as UTC, which a timestamp "
                "cannot hold; send a time inside them",
                {"value": read.isoformat()},
            ) from exc

    def __repr__(self) -> str:
        return f"LocalTimeIn({self.zone!r})"


__all__ = ["LocalTimeIn"]
