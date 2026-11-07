"""ADR 0207: a wall time sent with a named zone arrives as the instant it names.

``LocalTimeIn`` reads a value without a UTC offset as a local time in the zone it declares,
refuses one the clocks skip or repeat there, and leaves the published contract as a
``datetime``'s. A ``BaseSchema`` does not judge it: the zone names the instant, so it is no
escape.
"""

from __future__ import annotations

import copy
import pickle
import types
from datetime import UTC, datetime
from importlib.resources import files
from typing import Annotated, Any
from zoneinfo import ZoneInfo

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from pydantic import AfterValidator, BaseModel, ConfigDict, NaiveDatetime, TypeAdapter, ValidationError, create_model

from terp.core import BaseSchema, BootError, LocalTimeIn, ModuleSpec, Policy, create_app
from terp.core.local_time import _instant_in

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
    # The type's own reader sits behind the plain timestamp, with no refusal in front of it:
    # the walk knows the node by the reader's own function and leaves it.
    fields = _Meeting.__pydantic_core_schema__["schema"]["fields"]
    node = fields["starts_at"]["schema"]
    assert node["type"] == "function-after"
    assert node["function"]["function"].__func__ is LocalTimeIn._read
    assert node["schema"]["type"] == "datetime"


#: Another function bound to an instance of the type, which is not the type's reader.
_IMPOSTOR = types.MethodType(lambda _self, value: value, LocalTimeIn("Europe/Amsterdam"))


class _Impostor(BaseSchema):
    at: Annotated[datetime, AfterValidator(_IMPOSTOR)]


def test_the_walk_trusts_only_the_types_own_reader() -> None:
    # A function bound to an instance of the type is not its reader unless it is the type's
    # own, so the timestamp in front of it is judged like any other.
    with pytest.raises(ValidationError) as caught:
        _Impostor.model_validate({"at": "2026-11-06T10:00:00"})
    assert caught.value.errors()[0]["type"] == "timestamp_offset_required"


def test_a_reader_put_on_the_class_afterwards_is_not_trusted(monkeypatch: pytest.MonkeyPatch) -> None:
    # The walk knows the reader the type defined when the framework loaded, so a function put
    # on the class later is a function like any other, and the timestamp in front of it is
    # judged: the patch cannot read a time without an offset in a zone of its own choosing.
    monkeypatch.setattr(LocalTimeIn, "_read", lambda _self, value: value)

    class _Patched(BaseSchema):
        at: Annotated[datetime, LocalTimeIn("Europe/Amsterdam")]

    with pytest.raises(ValidationError) as caught:
        _Patched.model_validate({"at": "2026-11-06T10:00:00"})
    assert caught.value.errors()[0]["type"] == "timestamp_offset_required"


def _swapped(**fields: object) -> LocalTimeIn:
    """A local time declared in Amsterdam, then changed behind the type's back."""
    marker = LocalTimeIn("Europe/Amsterdam")
    for name, value in fields.items():
        object.__setattr__(marker, name, value)
    return marker


SWAPS = {
    "its zone for UTC": {"_zone": ZoneInfo("UTC")},
    "its zone for another place": {"_zone": ZoneInfo("Europe/London")},
    "both for UTC": {"zone": "UTC", "_zone": ZoneInfo("UTC")},
    "its name for none": {"zone": None},
    "its zone for text": {"_zone": "Europe/Amsterdam"},
}


@pytest.mark.parametrize("swap", sorted(SWAPS))
def test_a_zone_swapped_behind_the_types_back_is_not_trusted(swap: str) -> None:
    # object.__setattr__ reaches past the type's refusal of a change, and the swapped reader
    # would read a time without an offset as UTC. The walk reads the zone again, so the
    # timestamp in front of that reader is judged like any other.
    swapped = create_model("_Swapped", __base__=BaseSchema, at=(Annotated[datetime, _swapped(**SWAPS[swap])], ...))
    with pytest.raises(ValidationError) as caught:
        swapped.model_validate({"at": "2026-11-06T10:00:00"})
    assert caught.value.errors()[0]["type"] == "timestamp_offset_required"


def test_create_app_refuses_a_route_whose_zone_was_swapped() -> None:
    def slots(starts_after: datetime) -> dict[str, str]:  # pragma: no cover - never served
        return {}

    slots.__annotations__["starts_after"] = Annotated[datetime, _swapped(_zone=ZoneInfo("UTC"))]
    router = APIRouter()
    router.add_api_route("/slots", slots, response_model=dict[str, str])
    with pytest.raises(BootError, match="'starts_after'"):
        create_app([ModuleSpec(name="slots", router=router, policy=Policy.default())])


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


@pytest.mark.parametrize("zone", ["UTC", "Etc/UTC", "GMT", "Zulu", "Etc/GMT-1", "EST", "Factory"])
def test_a_key_that_names_no_place_is_refused_and_points_to_the_escape(zone: str) -> None:
    # Reading a wall time in UTC is NaiveMeansUtc's, which the rule counts; a fixed offset is
    # a sender's convention, not a place's wall time.
    with pytest.raises(ValueError, match="names no place's wall time") as caught:
        LocalTimeIn(zone)
    assert "NaiveMeansUtc" in str(caught.value)


@pytest.mark.parametrize("zone", ["localtime", "posixrules"])
def test_the_hosts_own_setting_is_no_zone_to_declare(zone: str) -> None:
    # Each host reads these its own way; one without a system zone database knows neither.
    with pytest.raises(ValueError, match="names no place's wall time|names no time zone this server knows"):
        LocalTimeIn(zone)


@pytest.mark.parametrize("zone", ["Atlantic/Reykjavik", "Africa/Abidjan", "Europe/London"])
def test_a_place_that_keeps_utc_today_is_still_a_place(zone: str) -> None:
    assert LocalTimeIn(zone).zone == zone


def test_it_reads_a_plain_datetime_and_says_where_it_goes() -> None:
    for declared in (
        Annotated[str, LocalTimeIn("Europe/Amsterdam")],
        Annotated[NaiveDatetime, LocalTimeIn("Europe/Amsterdam")],
        Annotated[datetime, AfterValidator(lambda value: value), LocalTimeIn("Europe/Amsterdam")],
    ):
        with pytest.raises(TypeError, match=r"goes directly after one: Annotated\[datetime, LocalTimeIn"):
            TypeAdapter(declared)


def test_it_cannot_be_subclassed() -> None:
    with pytest.raises(TypeError, match="cannot be subclassed"):

        class _Lenient(LocalTimeIn):
            pass


def test_it_is_fixed_once_declared_and_copies_as_itself() -> None:
    marker = LocalTimeIn("Europe/Amsterdam")
    with pytest.raises(AttributeError, match="fixed once declared"):
        marker.zone = "UTC"  # type: ignore[misc]
    with pytest.raises(AttributeError, match="fixed once declared"):
        del marker.zone
    assert copy.copy(marker) is marker
    assert copy.deepcopy(marker) is marker
    assert pickle.loads(pickle.dumps(marker)).zone == "Europe/Amsterdam"  # noqa: S301


def test_an_instant_outside_the_years_a_timestamp_holds_is_a_422_not_a_crash() -> None:
    # 0001-01-01 00:00 in Amsterdam is in year 0 as UTC; 9999-12-31 23:30 at -01:00 in 10000.
    assert _error("0001-01-01T00:00:00")["type"] == "timestamp_out_of_range"
    late = _error("9999-12-31T23:30:00-01:00")
    assert late["type"] == "timestamp_out_of_range"
    assert late["msg"].startswith("9999-12-31T23:30:00-01:00 falls outside the years 1 to 9999")


def test_a_wall_time_that_happens_once_is_its_instant_where_the_zone_data_disagrees() -> None:
    # Greenland kept -02 on 28 October 2023. The tzdata package's data reads one of the two
    # readings with a rule that had not started (-01), which does not read back, and the other
    # (-02), which does: the wall time happens once, and that is its instant.
    with (files("tzdata.zoneinfo") / "America" / "Nuuk").open("rb") as data:
        nuuk = ZoneInfo.from_file(data, key="America/Nuuk")
    assert _instant_in(datetime(2023, 10, 28, 23, 30), nuuk, "America/Nuuk") == datetime(
        2023, 10, 29, 1, 30, tzinfo=UTC
    )
    # Whichever data this host reads the zone from, the type takes it.
    host = TypeAdapter(Annotated[datetime, LocalTimeIn("America/Nuuk")])
    assert host.validate_python("2023-10-28T23:30:00") == datetime(2023, 10, 29, 1, 30, tzinfo=UTC)


def test_a_day_whose_midnight_the_clocks_skip_is_refused_like_any_such_time() -> None:
    havana = TypeAdapter(Annotated[datetime, LocalTimeIn("America/Havana")])
    with pytest.raises(ValidationError) as caught:
        havana.validate_python("2026-03-08")
    assert caught.value.errors()[0]["type"] == "local_time_skipped"


def test_the_fields_own_settings_read_the_value_first() -> None:
    class _Strict(BaseModel):
        model_config = ConfigDict(strict=True)
        starts_at: Amsterdam

    # Strict text from Python is refused as a plain strict datetime refuses it; strict JSON
    # text is read, and its wall time is the zone's.
    with pytest.raises(ValidationError) as caught:
        _Strict.model_validate({"starts_at": "2026-11-06T10:00:00"})
    assert caught.value.errors()[0]["type"] == "datetime_type"
    strict = _Strict.model_validate_json('{"starts_at": "2026-11-06T10:00:00"}')
    assert strict.starts_at == datetime(2026, 11, 6, 9, 0, tzinfo=UTC)


def test_it_names_itself_by_its_zone() -> None:
    marker = LocalTimeIn("Europe/Amsterdam")
    assert marker.zone == "Europe/Amsterdam"
    assert repr(marker) == "LocalTimeIn('Europe/Amsterdam')"
