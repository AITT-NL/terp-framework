"""ADR 0207: a wall time sent with a named zone arrives as the instant it names.

``LocalTimeIn`` reads a value without a UTC offset as a local time in the zone it declares,
refuses one the clocks skip or repeat there, and leaves the published contract as a
``datetime``'s. A ``BaseSchema`` does not judge it: the zone names the instant, so it is no
escape.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import TypeAdapter, ValidationError

from terp.core import BaseSchema, LocalTimeIn

Amsterdam = Annotated[datetime, LocalTimeIn("Europe/Amsterdam")]


class _Meeting(BaseSchema):
    starts_at: Amsterdam
    ends_at: datetime | None = None


class _Agenda(BaseSchema):
    slots: list[Amsterdam]
    moved_at: Amsterdam | None = None


def _starts_at(value: object) -> datetime:
    return _Meeting.model_validate({"starts_at": value}).starts_at


def _error(value: object) -> dict[str, Any]:
    with pytest.raises(ValidationError) as caught:
        _starts_at(value)
    (error,) = caught.value.errors()
    return dict(error)


@pytest.mark.parametrize(
    ("sent", "instant"),
    [
        ("2026-11-06T10:00:00", datetime(2026, 11, 6, 9, 0, tzinfo=UTC)),  # winter, +01:00
        ("2026-07-01T10:00", datetime(2026, 7, 1, 8, 0, tzinfo=UTC)),  # summer, +02:00
        ("2026-11-06", datetime(2026, 11, 5, 23, 0, tzinfo=UTC)),  # a day is its midnight there
        (datetime(2026, 11, 6, 10, 0), datetime(2026, 11, 6, 9, 0, tzinfo=UTC)),  # an object too
    ],
)
def test_a_wall_time_is_read_in_the_zone_and_arrives_as_an_instant(sent: object, instant: datetime) -> None:
    received = _starts_at(sent)
    assert received == instant
    assert received.utcoffset() is not None
    assert received.tzinfo is UTC


@pytest.mark.parametrize(
    ("sent", "instant"),
    [
        ("2026-11-06T10:00:00+05:00", datetime(2026, 11, 6, 5, 0, tzinfo=UTC)),
        ("2026-11-06T10:00:00Z", datetime(2026, 11, 6, 10, 0, tzinfo=UTC)),
        (datetime(2026, 11, 6, 10, 0, tzinfo=UTC), datetime(2026, 11, 6, 10, 0, tzinfo=UTC)),
        (1_762_423_200, datetime(2025, 11, 6, 10, 0, tzinfo=UTC)),  # a Unix time is UTC
    ],
)
def test_a_value_with_an_offset_is_the_instant_it_names(sent: object, instant: datetime) -> None:
    received = _starts_at(sent)
    assert received == instant
    assert received.tzinfo is UTC


def test_a_wall_time_the_clocks_skip_is_refused_saying_what_to_send() -> None:
    # 29 March 2026: Amsterdam goes from 02:00 to 03:00, so 02:30 never happens there.
    error = _error("2026-03-29T02:30:00")
    assert error["type"] == "local_time_skipped"
    assert error["loc"] == ("starts_at",)
    assert error["msg"] == (
        "2026-03-29T02:30:00 does not happen in Europe/Amsterdam, where the clocks skip it; "
        "send a time that happens there, or one with its UTC offset"
    )


def test_a_wall_time_the_clocks_repeat_is_refused_naming_both_instants() -> None:
    # 25 October 2026: Amsterdam goes from 03:00 back to 02:00, so 02:30 happens twice.
    error = _error("2026-10-25T02:30:00")
    assert error["type"] == "local_time_repeated"
    assert error["msg"] == (
        "2026-10-25T02:30:00 happens twice in Europe/Amsterdam, where the clocks repeat it; "
        "send it with its UTC offset, 2026-10-25T02:30:00+02:00 or 2026-10-25T02:30:00+01:00"
    )
    # Either instant, sent with its offset, is taken as itself.
    assert _starts_at("2026-10-25T02:30:00+02:00") == datetime(2026, 10, 25, 0, 30, tzinfo=UTC)
    assert _starts_at("2026-10-25T02:30:00+01:00") == datetime(2026, 10, 25, 1, 30, tzinfo=UTC)


def test_text_that_is_no_timestamp_keeps_the_types_own_error() -> None:
    assert _error("next tuesday")["type"] == "datetime_from_date_parsing"
    assert _error(["2026-11-06T10:00:00"])["type"] == "datetime_type"


def test_a_schema_does_not_judge_it_but_still_judges_its_neighbours() -> None:
    # The zone names the instant, so the refusal of ADR 0206 leaves this field to its type;
    # a plain datetime beside it still refuses a time without an offset.
    meeting = _Meeting.model_validate({"starts_at": "2026-11-06T10:00:00"})
    assert meeting.starts_at == datetime(2026, 11, 6, 9, 0, tzinfo=UTC)
    with pytest.raises(ValidationError) as caught:
        _Meeting.model_validate({"starts_at": "2026-11-06T10:00:00", "ends_at": "2026-11-06T11:00:00"})
    assert [(e["loc"], e["type"]) for e in caught.value.errors()] == [
        (("ends_at",), "timestamp_offset_required")
    ]


def test_the_schema_leaves_its_node_as_the_type_built_it() -> None:
    # The type's own reader sits in front of the plain timestamp, with no refusal between
    # them: the walk recognises the node as a local time's and leaves it.
    fields = _Meeting.__pydantic_core_schema__["schema"]["fields"]
    node = fields["starts_at"]["schema"]
    assert node["type"] == "function-before"
    assert isinstance(node["function"]["function"].__self__, LocalTimeIn)
    assert node["schema"]["type"] == "datetime"


def test_it_reads_each_item_of_a_list_and_an_optional_value() -> None:
    agenda = _Agenda.model_validate(
        {"slots": ["2026-11-06T10:00", "2026-11-06T11:00:00+01:00"], "moved_at": None}
    )
    assert agenda.slots == [
        datetime(2026, 11, 6, 9, 0, tzinfo=UTC),
        datetime(2026, 11, 6, 10, 0, tzinfo=UTC),
    ]
    assert agenda.moved_at is None
    with pytest.raises(ValidationError) as caught:
        _Agenda.model_validate({"slots": ["2026-11-06T10:00", "2026-03-29T02:30"]})
    assert [(e["loc"], e["type"]) for e in caught.value.errors()] == [
        (("slots", 1), "local_time_skipped")
    ]


def test_the_published_contract_is_a_datetimes() -> None:
    assert TypeAdapter(Amsterdam).json_schema() == TypeAdapter(datetime).json_schema()
    properties = _Meeting.model_json_schema()["properties"]
    assert properties["starts_at"] == {"format": "date-time", "title": "Starts At", "type": "string"}


def test_a_query_parameter_reads_the_zone_too_and_a_route_gets_the_instant() -> None:
    app = FastAPI()

    @app.get("/slots")
    def slots(starts_after: Amsterdam) -> dict[str, str]:
        return {"starts_after": starts_after.isoformat()}

    client = TestClient(app)
    taken = client.get("/slots", params={"starts_after": "2026-11-06T10:00"})
    assert taken.status_code == 200
    assert taken.json() == {"starts_after": "2026-11-06T09:00:00+00:00"}
    refused = client.get("/slots", params={"starts_after": "2026-03-29T02:30"})
    assert refused.status_code == 422
    assert refused.json()["detail"][0]["type"] == "local_time_skipped"


@pytest.mark.parametrize("zone", ["Mars/Olympus_Mons", "../etc/passwd", "", None])
def test_a_zone_the_server_does_not_know_is_refused_when_it_is_declared(zone: Any) -> None:
    with pytest.raises(ValueError, match="names no time zone this server knows") as caught:
        LocalTimeIn(zone)
    assert "Europe/Amsterdam" in str(caught.value)


def test_it_reads_a_datetime_and_says_so_when_declared_on_anything_else() -> None:
    with pytest.raises(TypeError, match=r"reads a datetime, not <class 'str'>"):
        TypeAdapter(Annotated[str, LocalTimeIn("Europe/Amsterdam")])


def test_it_names_itself_by_its_zone() -> None:
    marker = LocalTimeIn("Europe/Amsterdam")
    assert marker.zone == "Europe/Amsterdam"
    assert repr(marker) == "LocalTimeIn('Europe/Amsterdam')"
