"""A timestamp a client sends carries its UTC offset (ADR 0206).

A value with no offset names no instant, and read as UTC it puts a sender in any other zone
off by that zone's offset with no error anywhere. The published contract already requires
the offset (``format: date-time`` is RFC 3339's production), so the request boundary holds a
client to it: a ``BaseSchema`` body refuses such text at the field, and a declared filter
refuses such a bound. These tests pin each refusal, what is left alone (a value the server
built, a Unix time, the contract's text), and the one escape.
"""

from __future__ import annotations

import datetime as dt
from datetime import UTC, datetime
from typing import Annotated

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import AfterValidator
from pydantic import Field as PydanticField
from pydantic import ValidationError
from sqlmodel import Field

from terp.core import BaseSchema, BaseTable, BaseUpdateSchema, FilterField, NaiveMeansUtc, UtcDateTime
from terp.core.errors import ValidationFailedError
from terp.core.timestamps import OFFSET_REQUIRED

NAIVE = "2026-11-06T10:00:00"
AWARE = "2026-11-06T10:00:00Z"
AMSTERDAM = "2026-11-06T11:00:00+01:00"
INSTANT = datetime(2026, 11, 6, 10, 0, tzinfo=UTC)


class _Window(BaseSchema):
    title: str = ""
    starts_at: datetime
    ends_at: datetime | None = None
    marks: list[datetime] = []
    either: datetime | str | None = None


class _Aliased(BaseSchema):
    starts_at: datetime = PydanticField(alias="startsAt")


class _Outer(BaseSchema):
    window: _Window


class _WindowUpdate(BaseUpdateSchema):
    ends_at: datetime | None = None


class _SelfLenient(BaseSchema):
    """An app's own "assume UTC" validator, which is not the escape."""

    taken_at: Annotated[datetime, AfterValidator(lambda value: value.replace(tzinfo=UTC))] | None = None


class _Lenient(BaseSchema):
    taken_at: NaiveMeansUtc
    checked_at: NaiveMeansUtc | None = None


class _Reading(BaseTable, table=True):
    __tablename__ = "request_timestamp_reading"

    taken_at: datetime = Field(sa_type=UtcDateTime())


def _refusals(model: type[BaseSchema], data: object) -> list[tuple[tuple[str | int, ...], str, str]]:
    with pytest.raises(ValidationError) as caught:
        model.model_validate(data)
    return [(error["loc"], error["type"], error["msg"]) for error in caught.value.errors()]


# --------------------------------------------------------------------------- #
# a request body refuses a client's timestamp text without an offset
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("text", [NAIVE, "2026-11-06", "2026-11-06 10:00"])
def test_a_body_timestamp_without_an_offset_is_refused_at_its_field(text: str) -> None:
    assert _refusals(_Window, {"starts_at": text}) == [
        (("starts_at",), "timestamp_offset_required", OFFSET_REQUIRED)
    ]


def test_the_refusal_names_the_fix() -> None:
    assert "UTC offset" in OFFSET_REQUIRED
    assert AWARE in OFFSET_REQUIRED and AMSTERDAM in OFFSET_REQUIRED


@pytest.mark.parametrize("text", [AWARE, AMSTERDAM, "2026-11-06T10:00:00.123456+00:00"])
def test_a_body_timestamp_with_its_offset_keeps_it(text: str) -> None:
    window = _Window.model_validate({"starts_at": text})
    assert window.starts_at == datetime.fromisoformat(text.replace("Z", "+00:00"))
    assert window.starts_at.utcoffset() is not None


def test_every_field_without_an_offset_is_named_at_once() -> None:
    refusals = _refusals(
        _Window, {"starts_at": NAIVE, "ends_at": NAIVE, "marks": [AWARE, NAIVE, NAIVE]}
    )
    assert [loc for loc, _, _ in refusals] == [
        ("starts_at",),
        ("ends_at",),
        ("marks", 1),
        ("marks", 2),
    ]


def test_an_optional_field_left_out_or_null_is_not_a_timestamp() -> None:
    assert _Window.model_validate({"starts_at": AWARE, "ends_at": None}).ends_at is None
    assert _Window.model_validate({"starts_at": AWARE}).marks == []


def test_a_unix_time_is_utc_by_definition() -> None:
    assert _Window.model_validate({"starts_at": 1793872800}).starts_at.utcoffset() == dt.timedelta(0)
    assert _Window.model_validate({"starts_at": "1793872800"}).starts_at.utcoffset() == dt.timedelta(0)


def test_text_that_is_no_timestamp_at_all_keeps_its_own_error() -> None:
    ((loc, kind, _),) = _refusals(_Window, {"starts_at": "next tuesday"})
    assert loc == ("starts_at",) and kind != "timestamp_offset_required"


def test_the_alias_a_client_sends_is_the_place_named() -> None:
    assert _refusals(_Aliased, {"startsAt": NAIVE}) == [
        (("startsAt",), "timestamp_offset_required", OFFSET_REQUIRED)
    ]
    assert _Aliased.model_validate({"startsAt": AWARE}).starts_at == INSTANT


def test_a_nested_body_is_held_to_it_and_located_under_its_parent() -> None:
    assert _refusals(_Outer, {"window": {"starts_at": NAIVE}}) == [
        (("window", "starts_at"), "timestamp_offset_required", OFFSET_REQUIRED)
    ]


def test_an_update_body_is_held_to_it() -> None:
    assert _refusals(_WindowUpdate, {"version": 1, "ends_at": NAIVE}) == [
        (("ends_at",), "timestamp_offset_required", OFFSET_REQUIRED)
    ]


def test_an_annotated_timestamp_of_the_apps_own_is_judged_like_a_plain_one() -> None:
    """Only the escape steps around the refusal: a validator of the app's own that would
    read the value as UTC never sees text without an offset."""
    assert _refusals(_SelfLenient, {"taken_at": NAIVE}) == [
        (("taken_at",), "timestamp_offset_required", OFFSET_REQUIRED)
    ]


def test_a_field_that_also_takes_text_is_not_judged() -> None:
    """``datetime | str`` accepts any text by design, so it is not read as a timestamp."""
    window = _Window.model_validate({"starts_at": AWARE, "either": NAIVE})
    assert window.either is not None


def test_a_value_the_server_built_validates_as_before() -> None:
    """A row read back or a value computed in code is not a client's claim: an object, not
    text, so a response model built from it is untouched."""

    class Row:
        title = "kept"
        starts_at = datetime(2026, 11, 6, 10, 0)
        ends_at = None
        marks: list[datetime] = []
        either = None

    window = _Window.model_validate(Row())
    assert window.starts_at == datetime(2026, 11, 6, 10, 0)
    assert _Window(starts_at=datetime(2026, 11, 6, 10, 0)).starts_at.tzinfo is None


# --------------------------------------------------------------------------- #
# over HTTP: a 422 located at the field, and the contract's text unchanged
# --------------------------------------------------------------------------- #


def _app() -> FastAPI:
    app = FastAPI()

    @app.post("/windows")
    def create(window: _Window) -> dict[str, str]:
        return {"starts_at": window.starts_at.isoformat()}

    @app.post("/readings")
    def read(reading: _Lenient) -> dict[str, str]:
        return {"taken_at": reading.taken_at.isoformat()}

    @app.get("/readings")
    def since(after: NaiveMeansUtc) -> dict[str, str]:
        FilterField("after", _Reading.taken_at, op="gt").condition(after)
        return {"after": after.isoformat()}

    return app


def test_a_request_body_without_an_offset_is_a_422_at_the_field() -> None:
    response = TestClient(_app()).post("/windows", json={"starts_at": NAIVE})
    assert response.status_code == 422
    (detail,) = response.json()["detail"]
    assert detail["loc"] == ["body", "starts_at"]
    assert detail["type"] == "timestamp_offset_required"
    assert detail["msg"] == OFFSET_REQUIRED


def test_a_request_body_with_its_offset_is_taken() -> None:
    response = TestClient(_app()).post("/windows", json={"starts_at": AMSTERDAM})
    assert response.status_code == 200
    assert response.json() == {"starts_at": AMSTERDAM}


def test_the_published_contract_does_not_change() -> None:
    """``format: date-time`` already requires the offset, so refusing a value without one
    changes no schema: a client generated from the contract is unaffected, and the escape
    publishes the same text as a plain field."""
    schemas = _app().openapi()["components"]["schemas"]
    expected = {"type": "string", "format": "date-time"}
    assert {
        key: value for key, value in schemas["_Window"]["properties"]["starts_at"].items() if key != "title"
    } == expected
    assert {
        key: value for key, value in schemas["_Lenient"]["properties"]["taken_at"].items() if key != "title"
    } == expected


# --------------------------------------------------------------------------- #
# the escape: a value without an offset is read as UTC, and arrives aware
# --------------------------------------------------------------------------- #


def test_the_escape_reads_a_value_without_an_offset_as_utc() -> None:
    lenient = _Lenient.model_validate({"taken_at": NAIVE, "checked_at": NAIVE})
    assert lenient.taken_at == INSTANT and lenient.checked_at == INSTANT
    assert _Lenient.model_validate({"taken_at": AMSTERDAM}).taken_at.utcoffset() == dt.timedelta(hours=1)
    response = TestClient(_app()).post("/readings", json={"taken_at": NAIVE})
    assert response.json() == {"taken_at": "2026-11-06T10:00:00+00:00"}


def test_the_escape_takes_a_filter_parameter_as_utc_too() -> None:
    response = TestClient(_app()).get("/readings", params={"after": NAIVE})
    assert response.status_code == 200
    assert response.json() == {"after": "2026-11-06T10:00:00+00:00"}


# --------------------------------------------------------------------------- #
# a declared filter refuses a bound without an offset
# --------------------------------------------------------------------------- #


def test_a_filter_bound_without_an_offset_is_refused_naming_the_filter() -> None:
    field = FilterField("taken_after", _Reading.taken_at, op="gt")
    with pytest.raises(ValidationFailedError) as caught:
        field.condition(datetime(2026, 11, 6, 10, 0))
    assert caught.value.status_code == 400
    assert "'taken_after'" in str(caught.value.message) and "UTC offset" in str(caught.value.message)


def test_a_filter_list_is_refused_for_any_bound_without_an_offset() -> None:
    field = FilterField("taken_at", _Reading.taken_at, op="in")
    with pytest.raises(ValidationFailedError, match="UTC offset"):
        field.condition([INSTANT, datetime(2026, 11, 6, 10, 0)])
    assert field.condition([INSTANT]) is not None


def test_a_filter_bound_with_its_offset_and_a_date_are_taken() -> None:
    assert FilterField("taken_after", _Reading.taken_at, op="gt").condition(INSTANT) is not None
    assert FilterField("taken_on", _Reading.taken_at, op="gte").condition(dt.date(2026, 11, 6)) is not None
