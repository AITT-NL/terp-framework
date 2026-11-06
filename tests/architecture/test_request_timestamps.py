"""Timestamp text carries its UTC offset (ADR 0206).

A value with no offset names no instant, and read as UTC it puts a writer in any other zone off
by that zone's offset with no error anywhere. The published contract already asks for the
offset (``format: date-time`` is RFC 3339's production), so a ``BaseSchema`` refuses such text
wherever Pydantic reads a timestamp for it, and a declared filter refuses such a bound. These
tests pin each refusal and where it lands, what is left alone (an object the server built, a
Unix time, the framework's own job text, the contract's text), and the escape.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, NewType, TypeAliasType, TypedDict, Union

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import (
    AfterValidator,
    AliasChoices,
    AliasPath,
    BaseModel,
    Discriminator,
    FutureDatetime,
    GetCoreSchemaHandler,
    NaiveDatetime,
    Tag,
)
from pydantic import Field as PydanticField
from pydantic import ValidationError
from pydantic_core import CoreSchema
from sqlalchemy.pool import StaticPool
from sqlmodel import Field, Session, create_engine

from terp.core import (
    BaseSchema,
    BaseTable,
    BaseUpdateSchema,
    FilterField,
    InProcessJobQueue,
    JobCatalog,
    JobDefinition,
    NaiveMeansUtc,
    UtcDateTime,
    enqueue,
)
from terp.core.errors import ValidationFailedError
from terp.core.jobs import configure_jobs
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
    """An ``after`` validator of the app's own that would read the value as UTC never sees
    text without an offset: the refusal runs at the timestamp type, before it."""
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
    """``format: date-time`` already asks for the offset, so refusing a value without one
    changes no schema text: the committed contract stays as it is, and the escape publishes
    the same text as a plain field."""
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


# --------------------------------------------------------------------------- #
# judged wherever Pydantic validates a timestamp, at the place it reads it from
# --------------------------------------------------------------------------- #

_Stamp = NewType("_Stamp", datetime)


class _Shapes(BaseSchema):
    sequence: Sequence[datetime] = ()
    mapping: dict[str, datetime] = {}
    pair: tuple[datetime, int] | None = None
    nested: list[list[datetime]] = []
    stamp: _Stamp | None = None
    future: FutureDatetime | None = None
    either_day: datetime | dt.date | None = None
    or_number: datetime | int | None = None
    or_now: datetime | Literal["now"] | None = None
    naive_on_purpose: NaiveDatetime | None = None
    chosen: datetime | None = PydanticField(
        default=None, validation_alias=AliasChoices("chosen", "pickedAt")
    )
    pathed: datetime | None = PydanticField(
        default=None, validation_alias=AliasPath("window", "start")
    )


@pytest.mark.parametrize(
    ("data", "loc"),
    [
        ({"sequence": [NAIVE]}, ("sequence", 0)),
        ({"mapping": {"k": NAIVE}}, ("mapping", "k")),
        ({"pair": [NAIVE, 1]}, ("pair", 0)),
        ({"nested": [[AWARE, NAIVE]]}, ("nested", 0, 1)),
        ({"stamp": NAIVE}, ("stamp",)),
        ({"future": "2999-01-01T00:00:00"}, ("future",)),
        ({"either_day": NAIVE}, ("either_day", "datetime")),
        ({"or_number": NAIVE}, ("or_number", "datetime")),
        ({"naive_on_purpose": NAIVE}, ("naive_on_purpose",)),
        ({"pickedAt": NAIVE}, ("pickedAt",)),
        ({"window": {"start": NAIVE}}, ("window", "start")),
    ],
)
def test_every_shape_a_timestamp_is_read_through_is_judged(
    data: dict[str, object], loc: tuple[str | int, ...]
) -> None:
    assert (loc, "timestamp_offset_required", OFFSET_REQUIRED) in _refusals(_Shapes, data)


def test_a_member_beside_the_timestamp_still_takes_what_is_not_one() -> None:
    shapes = _Shapes.model_validate({"either_day": "2026-11-06", "or_number": 7, "or_now": "now"})
    assert (shapes.either_day, shapes.or_number, shapes.or_now) == (dt.date(2026, 11, 6), 7, "now")


def test_the_input_pydantic_reads_is_the_one_judged() -> None:
    """The alias wins over the field's own name, so the alias's text is the one judged."""
    assert _refusals(_Aliased, {"starts_at": AWARE, "startsAt": NAIVE}) == [
        (("startsAt",), "timestamp_offset_required", OFFSET_REQUIRED)
    ]


class _Booking(BaseSchema):
    booked_at: datetime
    window: _Window


def test_a_nested_timestamp_is_named_with_its_parent_in_the_same_error() -> None:
    assert [loc for loc, _, _ in _refusals(_Booking, {"booked_at": NAIVE, "window": {"starts_at": NAIVE}})] == [
        ("booked_at",),
        ("window", "starts_at"),
    ]


def test_a_schema_that_overrides_the_hook_is_refused_when_it_is_defined() -> None:
    with pytest.raises(TypeError, match="defines __get_pydantic_core_schema__"):

        class _Sneaky(BaseSchema):
            at: datetime

            @classmethod
            def __get_pydantic_core_schema__(
                cls, source: Any, handler: GetCoreSchemaHandler
            ) -> CoreSchema:
                return handler(source)


# --------------------------------------------------------------------------- #
# the framework reads back the text it wrote itself
# --------------------------------------------------------------------------- #


class _ReminderPayload(BaseSchema):
    remind_at: datetime


def test_a_job_reads_back_the_payload_the_framework_wrote() -> None:
    """A job's payload is written as text at enqueue and read back in the worker. A naive
    value the server built (ADR 0205 reads one as UTC) is written without an offset, and the
    read-back is the framework's own text, so it is not judged as a client's."""
    seen: list[datetime] = []
    job = JobDefinition(
        name="timestamps.remind",
        payload_schema=_ReminderPayload,
        handler=lambda _context, payload: seen.append(payload.remind_at),
    )
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    configure_jobs(JobCatalog([job]), queue=InProcessJobQueue(session_factory=lambda: Session(engine)))
    built = datetime.combine(dt.date(2026, 11, 6), dt.time(9, 0))
    with Session(engine) as session:
        enqueue(session, job=job, payload=_ReminderPayload(remind_at=built))
    assert seen == [built]


def test_text_an_app_hands_a_job_is_judged_like_any_other() -> None:
    job = JobDefinition(name="timestamps.text", payload_schema=_ReminderPayload, handler=lambda *_: None)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    configure_jobs(JobCatalog([job]), queue=InProcessJobQueue(session_factory=lambda: Session(engine)))
    with Session(engine) as session, pytest.raises(ValidationError, match="UTC offset"):
        enqueue(session, job=job, payload={"remind_at": NAIVE})


def test_a_refused_timestamp_is_named_beside_the_bodys_other_errors() -> None:
    refusals = _refusals(_Booking, {"booked_at": NAIVE})
    assert [(loc, kind) for loc, kind, _ in refusals] == [
        (("booked_at",), "timestamp_offset_required"),
        (("window",), "missing"),
    ]


def test_a_row_read_as_text_is_judged_like_any_other_text() -> None:
    """SQLite's driver returns a timestamp read by literal SQL as text, with no offset when it
    was stored without one, so a schema reading that row refuses it; the ORM's UtcDateTime
    hands the schema an aware value instead."""
    from sqlalchemy import text

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with Session(engine) as session:
        session.execute(text("CREATE TABLE visit (seen_at TEXT)"))
        session.execute(text("INSERT INTO visit VALUES ('2026-11-06 10:00:00.000000')"))
        row = session.execute(text("SELECT seen_at AS remind_at FROM visit")).mappings().one()
    assert _refusals(_ReminderPayload, row) == [
        (("remind_at",), "timestamp_offset_required", OFFSET_REQUIRED)
    ]


# --------------------------------------------------------------------------- #
# through every definition the schema refers to, and nothing outside it
# --------------------------------------------------------------------------- #


@dataclasses.dataclass
class _Span:
    start: datetime


class _SpanDict(TypedDict):
    start: datetime


type _Stamp695 = datetime
_Stamps = TypeAliasType("_Stamps", list[datetime])


class _Tree(BaseSchema):
    at: datetime
    child: _Tree | None = None


class _Defined(BaseSchema):
    span: _Span | None = None
    span_dict: _SpanDict | None = None
    stamp: _Stamp695 | None = None
    stamps: _Stamps | None = None
    tree: _Tree | None = None


@pytest.mark.parametrize(
    ("data", "loc"),
    [
        ({"span": {"start": NAIVE}}, ("span", "start")),
        ({"span_dict": {"start": NAIVE}}, ("span_dict", "start")),
        ({"stamp": NAIVE}, ("stamp",)),
        ({"stamps": [NAIVE]}, ("stamps", 0)),
        ({"tree": {"at": AWARE, "child": {"at": NAIVE}}}, ("tree", "child", "at")),
    ],
)
def test_a_timestamp_inside_a_definition_is_judged(data: dict[str, object], loc: tuple[str | int, ...]) -> None:
    assert _refusals(_Defined, data) == [(loc, "timestamp_offset_required", OFFSET_REQUIRED)]


class _SettingNames(BaseSchema):
    default: datetime | None = None
    expected: datetime | None = None
    metadata_: datetime | None = PydanticField(default=None, alias="metadata")
    ref: datetime | None = None
    cls: datetime | None = None
    serialization: datetime | None = None


@pytest.mark.parametrize("name", ["default", "expected", "metadata", "ref", "cls", "serialization"])
def test_a_field_named_like_a_schema_setting_is_judged(name: str) -> None:
    assert _refusals(_SettingNames, {name: NAIVE}) == [((name,), "timestamp_offset_required", OFFSET_REQUIRED)]


class _Kept(BaseSchema):
    kind: Literal["kept"] = "kept"
    at: datetime


class _Moved(BaseSchema):
    kind: Literal["moved"] = "moved"
    at: datetime


def _which(value: object) -> str:
    kind = value.get("kind") if isinstance(value, dict) else getattr(value, "kind", None)
    return "default" if kind == "kept" else "moved"


class _Tagged(BaseSchema):
    either: Annotated[
        Union[Annotated[_Kept, Tag("default")], Annotated[_Moved, Tag("moved")]], Discriminator(_which)
    ]
    listed: list[datetime] | str | None = None


def test_a_tagged_member_is_judged_under_its_tag_whatever_the_tag_is_called() -> None:
    assert _refusals(_Tagged, {"either": {"kind": "kept", "at": NAIVE}}) == [
        (("either", "default", "at"), "timestamp_offset_required", OFFSET_REQUIRED)
    ]


def test_a_union_member_is_located_by_the_name_pydantic_gives_it() -> None:
    (loc, kind, _), *_ = _refusals(_Tagged, {"either": {"kind": "moved", "at": AWARE}, "listed": [NAIVE]})
    assert (loc, kind) == (("listed", "list[datetime]", 0), "timestamp_offset_required")


class _PlainSpan(BaseModel):
    start: datetime


class _PlainLenientSpan(BaseModel):
    start: NaiveMeansUtc


def test_a_nested_model_that_brings_its_own_validator_is_refused_when_defined() -> None:
    """Pydantic validates such a model with its own complete validator, which does not judge,
    so the schema around it would let its timestamp through; it is refused instead."""
    with pytest.raises(TypeError, match="nests _PlainSpan, which brings its own Pydantic validator"):

        class _Nests(BaseSchema):
            span: _PlainSpan

    class _NestsLenient(BaseSchema):
        span: _PlainLenientSpan

    assert _NestsLenient.model_validate({"span": {"start": NAIVE}}).span.start == INSTANT


def test_a_plain_model_around_the_same_type_stays_as_it_was() -> None:
    class _PlainParent(BaseModel):
        span: _Span

    assert _PlainParent.model_validate({"span": {"start": NAIVE}}).span.start.tzinfo is None


def test_a_class_between_that_defines_a_hook_is_refused_when_defined() -> None:
    with pytest.raises(TypeError, match="defines __pydantic_init_subclass__"):

        class _Quiet(BaseSchema):
            @classmethod
            def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
                return None


def test_a_context_spelled_like_the_frameworks_own_is_not_trusted() -> None:
    with pytest.raises(ValidationError, match="UTC offset"):
        _ReminderPayload.model_validate({"remind_at": NAIVE}, context={"terp.timestamps.server-text": True})
