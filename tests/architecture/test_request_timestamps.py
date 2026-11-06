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
    ConfigDict,
    Discriminator,
    FutureDatetime,
    GetCoreSchemaHandler,
    NaiveDatetime,
    RootModel,
    Tag,
    create_model,
    model_validator,
)
from pydantic import Field as PydanticField
from pydantic import ValidationError
from pydantic.dataclasses import dataclass as pydantic_dataclass
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
    type: datetime | None = None
    default: datetime | None = None
    expected: datetime | None = None
    metadata_: datetime | None = PydanticField(default=None, alias="metadata")
    ref: datetime | None = None
    cls: datetime | None = None
    serialization: datetime | None = None


@pytest.mark.parametrize("name", ["type", "default", "expected", "metadata", "ref", "cls", "serialization"])
def test_a_field_named_like_a_schema_setting_is_judged(name: str) -> None:
    assert _refusals(_SettingNames, {name: NAIVE}) == [((name,), "timestamp_offset_required", OFFSET_REQUIRED)]


def test_fields_named_type_and_default_are_each_judged() -> None:
    """A model's mapping of field names holds a field named "type" beside one named "default",
    so the mapping is not mistaken for a schema node of some kind."""
    assert [loc for loc, _, _ in _refusals(_SettingNames, {"type": NAIVE, "default": NAIVE})] == [
        ("type",),
        ("default",),
    ]


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


# --------------------------------------------------------------------------- #
# a nested class with its own validator is judged in front of it
# --------------------------------------------------------------------------- #


class _PlainSpan(BaseModel):
    start: datetime


class _PlainLenientSpan(BaseModel):
    start: NaiveMeansUtc


class _AliasOnlySpan(BaseModel):
    """Its own config reads the alias only, unlike a ``BaseSchema``, which reads both."""

    start: datetime = PydanticField(alias="startsAt")


class _StrictSpan(BaseModel):
    model_config = ConfigDict(strict=True)

    start: datetime


class _CheckedSpan(BaseModel):
    start: datetime

    @model_validator(mode="after")
    def _kept(self) -> _CheckedSpan:
        return self


class _Stamped(RootModel[datetime]):
    pass


@pydantic_dataclass
class _PydanticSpan:
    start: datetime


class _PlainTree(BaseModel):
    at: datetime
    kids: list[_PlainTree] = []


class _Visit(BaseTable, table=True):
    __tablename__ = "request_timestamp_visit"

    seen_at: datetime = Field(sa_type=UtcDateTime())


_FrameworkPoint = create_model("_FrameworkPoint", start=(datetime, ...))
_FrameworkGroup = create_model("_FrameworkGroup", series=(list[_FrameworkPoint], ...))


class _Nests(BaseSchema):
    span: _PlainSpan | None = None
    spans: list[_PlainSpan] = []
    either: _PlainSpan | int | None = None
    aliased: _AliasOnlySpan | None = None
    strict: _StrictSpan | None = None
    checked: _CheckedSpan | None = None
    stamp: _Stamped | None = None
    dataclass_span: _PydanticSpan | None = None
    tree: _PlainTree | None = None
    visits: list[_Visit] = []
    group: _FrameworkGroup | None = None
    lenient: _PlainLenientSpan | None = None


@pytest.mark.parametrize(
    ("data", "loc"),
    [
        ({"span": {"start": NAIVE}}, ("span", "start")),
        ({"spans": [{"start": AWARE}, {"start": NAIVE}]}, ("spans", 1, "start")),
        ({"either": {"start": NAIVE}}, ("either", "_PlainSpan", "start")),
        ({"aliased": {"startsAt": NAIVE}}, ("aliased", "startsAt")),
        ({"strict": {"start": NAIVE}}, ("strict", "start")),
        ({"checked": {"start": NAIVE}}, ("checked", "start")),
        ({"stamp": NAIVE}, ("stamp",)),
        ({"dataclass_span": {"start": NAIVE}}, ("dataclass_span", "start")),
        ({"tree": {"at": AWARE, "kids": [{"at": AWARE, "kids": [{"at": NAIVE}]}]}}, ("tree", "kids", 0, "kids", 0, "at")),
        ({"visits": [{"seen_at": NAIVE}]}, ("visits", 0, "seen_at")),
        ({"group": {"series": [{"start": NAIVE}]}}, ("group", "series", 0, "start")),
    ],
)
def test_a_nested_class_with_its_own_validator_is_judged_in_front_of_it(
    data: dict[str, object], loc: tuple[str | int, ...]
) -> None:
    """Pydantic validates a complete plain model, a Pydantic dataclass, a root model, a table and
    a model the framework builds with its own validator, whatever schema surrounds it, so what
    it is given is judged first, wherever it sits."""
    assert (loc, "timestamp_offset_required", OFFSET_REQUIRED) in _refusals(_Nests, data)


def test_a_nested_class_with_its_offsets_validates_as_its_own_validator_does() -> None:
    nests = _Nests.model_validate(
        {"span": {"start": AWARE}, "stamp": AMSTERDAM, "dataclass_span": {"start": AWARE}, "lenient": {"start": NAIVE}}
    )
    assert (type(nests.span), nests.span.start) == (_PlainSpan, INSTANT)
    assert (type(nests.stamp), nests.stamp.root) == (_Stamped, INSTANT)
    assert type(nests.dataclass_span) is _PydanticSpan
    assert nests.lenient is not None and nests.lenient.start == INSTANT


def test_a_nested_class_the_server_built_goes_straight_on() -> None:
    """An instance was built already, and a row's values are objects: neither is text."""
    built = datetime(2026, 11, 6, 10, 0)
    span, visit = _PlainSpan(start=built), _Visit(seen_at=INSTANT)

    class _Row:
        at = built
        kids: list[object] = []

    nests = _Nests.model_validate({"span": span, "visits": [visit], "stamp": _Stamped(built)})
    assert nests.span is span and nests.visits == [visit] and nests.stamp is not None
    assert _Nests.model_validate({"tree": _Row()}, from_attributes=True).tree == _PlainTree(at=built)


def test_a_nested_class_is_judged_under_its_own_config() -> None:
    """A model that reads only an alias leaves a value under its field name unread, so that
    value is not judged; its own error says the alias is missing."""
    assert _refusals(_Nests, {"aliased": {"start": NAIVE}}) == [
        (("aliased", "startsAt"), "missing", "Field required")
    ]


def test_a_nested_class_reports_its_own_errors_once() -> None:
    """A refusal comes beside the outer schema's own errors; the nested class's other errors
    are its own validator's, which reads its input once the timestamps in it are taken."""
    assert [(loc, kind) for loc, kind, _ in _refusals(_Nests, {"span": {"start": NAIVE}, "spans": "x"})] == [
        (("span", "start"), "timestamp_offset_required"),
        (("spans",), "list_type"),
    ]
    assert [(loc, kind) for loc, kind, _ in _refusals(_Nests, {"span": {"start": "soon"}})] == [
        (("span", "start"), "datetime_from_date_parsing")
    ]


# --------------------------------------------------------------------------- #
# schemas that refer to each other, and a union that picks by a tag
# --------------------------------------------------------------------------- #


class _Ping(BaseSchema):
    at: datetime
    pong: _Pong | None = None
    pair: tuple[_Pong, datetime, _PlainSpan] | int | None = None


class _Pong(BaseSchema):
    at: datetime | None = None
    ping: _Ping | None = None


_Ping.model_rebuild()


def test_schemas_that_refer_to_each_other_are_each_judged() -> None:
    assert [loc for loc, _, _ in _refusals(_Pong, {"ping": {"at": AWARE, "pong": {"at": NAIVE}}})] == [
        ("ping", "pong", "at")
    ]
    assert [loc for loc, _, _ in _refusals(_Ping, {"at": NAIVE, "pong": {"ping": {"at": NAIVE}}})] == [
        ("at",),
        ("pong", "ping", "at"),
    ]


@pytest.mark.parametrize(
    ("pair", "place"), [([{}, NAIVE, {"start": AWARE}], (1,)), ([{}, AWARE, {"start": NAIVE}], (2, "start"))]
)
def test_a_member_that_refers_back_is_named_as_pydantic_names_it(
    pair: list[object], place: tuple[str | int, ...]
) -> None:
    """The member is named as Pydantic built it, before its timestamps were held, even where it
    was first held while the schema it refers to was still being built."""
    (loc, kind, _), *_ = _refusals(_Pong, {"ping": {"at": AWARE, "pair": pair}})
    assert (loc, kind) == (("ping", "pair", "tuple[_Pong, datetime, _PlainSpan]", *place), "timestamp_offset_required")


class _Leaf(BaseSchema):
    kind: Literal["leaf"] = "leaf"
    at: datetime


class _Branch(BaseSchema):
    kind: Literal["branch"] = "branch"
    child: Annotated[Union[_Leaf, _Branch], PydanticField(discriminator="kind")] | None = None


def test_a_recursive_union_still_picks_its_member_by_its_tag() -> None:
    """Pydantic settles such a union's tag once the schema is built, from its own metadata; a
    held copy of the union that shared it would be left a union that tries every member."""
    assert _refusals(_Branch, {"child": {"kind": "twig"}})[0][:2] == (("child",), "union_tag_invalid")
    assert _refusals(_Branch, {"child": {"kind": "branch", "child": {"kind": "leaf", "at": NAIVE}}}) == [
        (("child", "branch", "child", "leaf", "at"), "timestamp_offset_required", OFFSET_REQUIRED)
    ]


def test_a_plain_choice_of_a_recursive_union_is_refused_when_its_schema_is_built() -> None:
    """Pydantic picks a choice of such a union by the tag in the choice's own fields, which a
    choice judged in front of its own validator no longer shows, so it is refused, naming why.
    A class that refers to itself in a function is built at its first use, here a rebuild."""

    class _PlainLeaf(BaseModel):
        kind: Literal["plain"] = "plain"
        at: datetime

    class _Tangle(BaseSchema):
        kind: Literal["tangle"] = "tangle"
        child: Annotated[Union[_PlainLeaf, _Tangle], PydanticField(discriminator="kind")] | None = None

    with pytest.raises(TypeError, match=r"_PlainLeaf as a choice of a discriminated union .* derive"):
        _Tangle.model_rebuild()


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
