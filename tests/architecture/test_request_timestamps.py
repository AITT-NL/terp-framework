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
import importlib.util
import sys
import types
from collections.abc import Sequence
from decimal import Decimal
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
    BeforeValidator,
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
from sqlmodel import Field, Session, SQLModel, create_engine, select

from terp.core import (
    BaseSchema,
    BaseTable,
    BaseUpdateSchema,
    FilterField,
    FilterOp,
    InProcessJobQueue,
    JobCatalog,
    JobDefinition,
    NaiveMeansUtc,
    UtcDateTime,
    enqueue,
)
from terp.core.errors import ValidationFailedError
from terp.core.jobs import configure_jobs
from terp.core.timestamps import (
    OFFSET_REQUIRED,
    _reading_server_text,
    refuse_timestamp_text_without_offset,
)

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


class _Diary(BaseTable, table=True):
    __tablename__ = "request_timestamp_diary"

    on: dt.date


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


_CONTRACT = '''
import dataclasses
from datetime import datetime
from typing import Annotated, Literal, TypedDict, TypeAliasType, Union

from pydantic import BaseModel, Field


class Span(BaseModel):
    start: datetime


@dataclasses.dataclass
class Window:
    """A stdlib dataclass, which the schema around it validates."""

    start: datetime


class Mark(TypedDict):
    at: datetime


Marks = TypeAliasType("Marks", list[datetime])


class Leaf(Base):
    kind: Literal["leaf"] = "leaf"
    at: datetime


class Branch(Base):
    kind: Literal["branch"] = "branch"
    child: Annotated[Union[Leaf, Branch], Field(discriminator="kind")] | None = None


class Ping(Base):
    at: datetime
    pong: Pong | None = None


class Pong(Base):
    at: datetime | None = None
    ping: Ping | None = None


class Holder(Base):
    span: Span
    window: Window
    mark: Mark
    marks: Marks = []
    keyed: dict[str, datetime] | int = 0
    branch: Branch | None = None
    ping: Ping | None = None
'''


class _Twin(SQLModel):
    """What a BaseSchema is without its hook: an SQLModel with BaseSchema's config."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True, str_strip_whitespace=True)


#: The base each copy of the contract's schemas is declared over: BaseSchema, and its twin.
_CONTRACT_BASES = {
    "_contract_held": "from terp.core import BaseSchema as Base\n",
    "_contract_twin": (
        "from pydantic import ConfigDict\nfrom sqlmodel import SQLModel\n\n\n"
        "class Base(SQLModel):\n"
        "    model_config = ConfigDict(from_attributes=True, populate_by_name=True, str_strip_whitespace=True)\n"
    ),
}


@pytest.fixture(scope="module")
def contract(tmp_path_factory: pytest.TempPathFactory) -> dict[str, types.ModuleType]:
    """The contract's schemas twice, as modules of their own so their names are the same."""
    root = tmp_path_factory.mktemp("contract")
    modules: dict[str, types.ModuleType] = {}
    for name, base in _CONTRACT_BASES.items():
        path = root / f"{name}.py"
        path.write_text(f"from __future__ import annotations\n\n{base}{_CONTRACT}", encoding="utf-8")
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        modules[name] = module
    return modules


def _contract_app(module: types.ModuleType) -> FastAPI:
    holder = module.__dict__["Holder"]

    def create(body: Any) -> Any:
        return body

    create.__annotations__ = {"body": holder, "return": holder}  # this file's own are strings
    app = FastAPI()
    app.post("/holders")(create)
    return app


@pytest.mark.parametrize("mode", ["validation", "serialization"])
def test_the_published_contract_is_the_plain_schemas_own(
    contract: dict[str, types.ModuleType], mode: Literal["validation", "serialization"]
) -> None:
    """The refusal is no part of a JSON schema, and a held copy of a definition is named as
    Pydantic names the original, so a schema publishes exactly what it would without its hook:
    with a nested plain model, a stdlib dataclass, a TypedDict, a type alias, a recursive union
    and schemas that refer to each other."""
    held, twin = (contract[name].__dict__["Holder"] for name in ("_contract_held", "_contract_twin"))
    assert held.model_json_schema(mode=mode) == twin.model_json_schema(mode=mode)


def test_the_published_api_contract_is_the_plain_schemas_own(contract: dict[str, types.ModuleType]) -> None:
    held = _contract_app(contract["_contract_held"]).openapi()
    assert held == _contract_app(contract["_contract_twin"]).openapi()
    assert {"Span", "Window", "Mark", "Marks", "Leaf", "Holder-Input", "Ping-Input"} <= set(
        held["components"]["schemas"]
    )


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


def test_a_filter_bound_given_as_text_is_read_as_a_timestamp_first() -> None:
    """A route's parameter arrives parsed, but the app's own code can hand a filter text; on a
    timestamp column it is read as a request's would be, and the bound is the instant it names."""
    field = FilterField("taken_after", _Reading.taken_at, op="gt")
    for text in (NAIVE, "soon"):
        with pytest.raises(ValidationFailedError, match="'taken_after' needs a date and time with its UTC offset"):
            field.condition(text)
    assert field.condition(AMSTERDAM).right.value == INSTANT  # type: ignore[attr-defined]
    assert FilterField("taken_at", _Reading.taken_at, op="in").condition([AWARE]) is not None


def test_a_filter_bound_given_as_text_elsewhere_is_left_as_it_is() -> None:
    assert FilterField("id", _Reading.id, op="eq").condition(NAIVE).right.value == NAIVE  # type: ignore[attr-defined]

    class _NamesNoType:
        @property
        def python_type(self) -> type:
            raise NotImplementedError

    class _Opaque:
        type = _NamesNoType()

        def __eq__(self, other: object) -> Any:
            return ("eq", other)

        __hash__ = object.__hash__

    assert FilterField("opaque", _Opaque(), op="eq").condition(NAIVE) == ("eq", NAIVE)  # type: ignore[arg-type]


def test_a_filter_bound_with_its_offset_is_taken() -> None:
    assert FilterField("taken_after", _Reading.taken_at, op="gt").condition(INSTANT) is not None


@pytest.mark.parametrize("op", ["eq", "gte", "lt"])
def test_a_calendar_day_on_a_timestamp_filter_without_a_zone_is_refused(op: FilterOp) -> None:
    """A day names no instant until it names the zone whose day it is, so a filter that
    declares none refuses it, as a request body refuses a bare date for a timestamp."""
    with pytest.raises(ValidationFailedError, match="'taken_on' needs a date and time with its UTC offset"):
        FilterField("taken_on", _Reading.taken_at, op=op).condition(dt.date(2026, 11, 6))
    with pytest.raises(ValidationFailedError, match="UTC offset"):
        FilterField("taken_on", _Reading.taken_at, op="in").condition([dt.date(2026, 11, 6)])


def test_a_calendar_day_on_a_column_of_days_is_compared_as_it_always_was() -> None:
    assert FilterField("on", _Diary.on, op="gte").condition(dt.date(2026, 11, 6)).right.value == dt.date(2026, 11, 6)  # type: ignore[attr-defined]


#: Four readings around 6 November in Amsterdam (UTC+1): the minute before it starts, its
#: first minute, its last minute, and the first minute after it.
_AROUND_THE_DAY = {
    "before": datetime(2026, 11, 5, 22, 59, tzinfo=UTC),
    "first": datetime(2026, 11, 5, 23, 0, tzinfo=UTC),
    "last": datetime(2026, 11, 6, 22, 59, tzinfo=UTC),
    "after": datetime(2026, 11, 6, 23, 0, tzinfo=UTC),
}


def _matching(condition: Any) -> set[str]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine, tables=[_Reading.__table__])  # type: ignore[list-item]
    names = {instant: name for name, instant in _AROUND_THE_DAY.items()}
    with Session(engine) as session:
        session.add_all(_Reading(taken_at=instant) for instant in _AROUND_THE_DAY.values())
        session.commit()
        rows = session.exec(select(_Reading).where(condition)).all()
        return {names[row.taken_at] for row in rows}


@pytest.mark.parametrize(
    ("op", "matched"),
    [
        ("eq", {"first", "last"}),
        ("ne", {"before", "after"}),
        ("lt", {"before"}),
        ("lte", {"before", "first", "last"}),
        ("gt", {"after"}),
        ("gte", {"first", "last", "after"}),
    ],
)
def test_a_filter_that_declares_a_zone_compares_a_day_as_the_whole_of_it(op: FilterOp, matched: set[str]) -> None:
    field = FilterField("taken_on", _Reading.taken_at, op=op, zone="Europe/Amsterdam")
    assert _matching(field.condition(dt.date(2026, 11, 6))) == matched


def test_a_filter_that_declares_a_zone_takes_a_list_of_days_and_an_instant_as_one() -> None:
    days = FilterField("taken_on", _Reading.taken_at, op="in", zone="Europe/Amsterdam")
    assert _matching(days.condition([dt.date(2026, 11, 5), dt.date(2026, 11, 7)])) == {"before", "after"}
    assert _matching(days.condition([_AROUND_THE_DAY["last"]])) == {"last"}
    since = FilterField("taken_since", _Reading.taken_at, op="gte", zone="Europe/Amsterdam")
    assert _matching(since.condition(_AROUND_THE_DAY["last"])) == {"last", "after"}
    with pytest.raises(ValidationFailedError, match="UTC offset"):
        since.condition(datetime(2026, 11, 6, 10, 0))


@pytest.mark.parametrize(
    ("zone", "day"),
    [("Asia/Tokyo", dt.date(1, 1, 1)), ("America/New_York", dt.date(9999, 12, 31)), ("UTC", dt.date(9999, 12, 31))],
)
def test_a_day_at_the_edge_of_the_years_a_timestamp_holds_is_a_400(zone: str, day: dt.date) -> None:
    # Midnight on 1 January of year 1 east of UTC is in year 0, and the day after 31 December
    # 9999 is in no year a date holds: each overflowed into a 500.
    field = FilterField("taken_on", _Reading.taken_at, op="eq", zone=zone)
    with pytest.raises(ValidationFailedError, match="'taken_on' is outside the range of a timestamp"):
        field.condition(day)


def test_a_day_the_clocks_go_back_on_is_twenty_five_hours_long() -> None:
    field = FilterField("taken_on", _Reading.taken_at, op="eq", zone="Europe/Amsterdam")
    start, end = (clause.right.value for clause in field.condition(dt.date(2026, 10, 25)).clauses)  # type: ignore[attr-defined]
    assert (start, end - start) == (datetime(2026, 10, 24, 22, 0, tzinfo=UTC), dt.timedelta(hours=25))


@pytest.mark.parametrize(
    ("declared", "message"),
    [
        ({"op": "like"}, "declares op 'like'; choose one of eq, ne"),
        ({"zone": "Mars/Olympus"}, "is not a time zone this server knows"),
        ({"zone": "Europe/Amsterdam", "column": "on"}, "on a column that holds none; remove the zone"),
    ],
)
def test_a_filter_declared_wrongly_is_refused_when_it_is_declared(declared: dict[str, str], message: str) -> None:
    column = _Diary.on if declared.pop("column", None) else _Reading.taken_at
    with pytest.raises(ValueError, match=message):
        FilterField("taken_on", column, **declared)  # type: ignore[arg-type]


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


class _Slot(BaseSchema):
    at: datetime


class _SlotsPayload(BaseSchema):
    slots: list[_Slot]


def test_a_job_reads_back_a_nested_payload_the_framework_wrote() -> None:
    """SQLModel validates a nested schema afresh, with no validation context, so the worker's
    trust is a context variable, which every schema its read reaches sees."""
    seen: list[datetime] = []
    job = JobDefinition(
        name="timestamps.slots",
        payload_schema=_SlotsPayload,
        handler=lambda _context, payload: seen.append(payload.slots[0].at),
    )
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    configure_jobs(JobCatalog([job]), queue=InProcessJobQueue(session_factory=lambda: Session(engine)))
    built = datetime(2026, 11, 6, 9, 0)
    with Session(engine) as session:
        enqueue(session, job=job, payload=_SlotsPayload(slots=[_Slot(at=built)]))
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
    keyed: dict[str, datetime] | int | None = None
    spanned: _SpanDict | int | None = None


def test_a_tagged_member_is_judged_under_its_tag_whatever_the_tag_is_called() -> None:
    assert _refusals(_Tagged, {"either": {"kind": "kept", "at": NAIVE}}) == [
        (("either", "default", "at"), "timestamp_offset_required", OFFSET_REQUIRED)
    ]


def test_a_union_member_is_located_by_the_name_pydantic_gives_it() -> None:
    (loc, kind, _), *_ = _refusals(_Tagged, {"either": {"kind": "moved", "at": AWARE}, "listed": [NAIVE]})
    assert (loc, kind) == (("listed", "list[datetime]", 0), "timestamp_offset_required")


def test_a_union_member_held_as_a_definition_is_named_as_the_original() -> None:
    (loc, kind, _), *_ = _refusals(_Tagged, {"either": {"kind": "moved", "at": AWARE}, "spanned": {"start": NAIVE}})
    assert (loc, kind) == (("spanned", "_SpanDict", "start"), "timestamp_offset_required")


def test_a_union_member_is_named_under_the_config_it_is_read_with() -> None:
    """BaseSchema strips its strings, so Pydantic names a str inside a member a constrained one."""
    (loc, kind, _), *_ = _refusals(_Tagged, {"either": {"kind": "moved", "at": AWARE}, "keyed": {"k": NAIVE}})
    assert (loc, kind) == (("keyed", "dict[constrained-str,datetime]", "k"), "timestamp_offset_required")


# --------------------------------------------------------------------------- #
# a nested class with its own validator reads its own fields
# --------------------------------------------------------------------------- #


class _PlainSpan(BaseModel):
    start: datetime


class _Charge(BaseModel):
    """A model whose own before validator rewrites what it is given, as many do."""

    at: datetime
    amount: Decimal

    @model_validator(mode="before")
    @classmethod
    def _from_cents(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data["amount"] = Decimal(data["amount"]) / 100
        return data


class _Stamped(RootModel[datetime]):
    pass


@pydantic_dataclass
class _PydanticSpan:
    start: datetime


class _Visit(BaseTable, table=True):
    __tablename__ = "request_timestamp_visit"

    seen_at: datetime = Field(sa_type=UtcDateTime())


_FrameworkPoint = create_model("_FrameworkPoint", start=(datetime, ...))


class _StampedChoice(BaseModel):
    x: int
    at: datetime | None = None


class _BareChoice(BaseModel):
    x: int
    y: str = ""


class _Nests(BaseSchema):
    span: _PlainSpan | None = None
    charge: _Charge | None = None
    stamp: _Stamped | None = None
    dataclass_span: _PydanticSpan | None = None
    visits: list[_Visit] = []
    point: _FrameworkPoint | None = None  # type: ignore[valid-type]
    either: _StampedChoice | _BareChoice | None = None


class _VisitsTwin(_Twin):
    visits: list[_Visit] = []


def test_a_nested_class_with_its_own_validator_reads_its_own_fields() -> None:
    """Pydantic validates a plain model, a root model, a Pydantic dataclass, a table and a model
    the framework builds with the class's own validator, whatever schema surrounds it. Such a
    class is left to that validator, as a request model that is not a BaseSchema is (ADR 0206,
    Open): derive it from BaseSchema to hold its timestamps."""
    naive = datetime(2026, 11, 6, 10, 0)
    nests = _Nests.model_validate(
        {
            "span": {"start": NAIVE},
            "stamp": NAIVE,
            "dataclass_span": {"start": NAIVE},
            "visits": [{"seen_at": NAIVE}],
            "point": {"start": NAIVE},
        }
    )
    assert nests.span is not None and nests.span.start == naive
    assert nests.stamp is not None and nests.stamp.root == naive
    assert nests.dataclass_span is not None and nests.dataclass_span.start == naive
    assert nests.point is not None and nests.point.start == naive
    # A table does not validate what it is constructed from, nested or not.
    assert nests.visits[0].seen_at == _VisitsTwin.model_validate({"visits": [{"seen_at": NAIVE}]}).visits[0].seen_at


def test_a_nested_class_validates_exactly_as_its_own_validator_does() -> None:
    """Its own validators run once, on what it is given, and a union picks among such classes as
    it would with no schema around them."""
    nests = _Nests.model_validate({"charge": {"at": AWARE, "amount": 1250}, "either": {"x": 1, "y": "a"}})
    assert nests.charge is not None and nests.charge.amount == Decimal("12.5")
    assert nests.either == _BareChoice(x=1, y="a")


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


def test_a_member_that_refers_back_is_named_as_pydantic_names_it() -> None:
    """The member is named as Pydantic built it, before its timestamps were held, even where it
    was first held while the schema it refers to was still being built."""
    (loc, kind, _), *_ = _refusals(_Pong, {"ping": {"at": AWARE, "pair": [{}, NAIVE, {"start": AWARE}]}})
    assert (loc, kind) == (("ping", "pair", "tuple[_Pong, datetime, _PlainSpan]", 1), "timestamp_offset_required")


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


def test_a_plain_choice_of_a_recursive_union_keeps_its_tag_and_its_own_validator() -> None:
    """A class that refers to itself in a function is built at its first use, here a rebuild."""

    class _PlainLeaf(BaseModel):
        kind: Literal["plain"] = "plain"
        at: datetime

    class _Tangle(BaseSchema):
        kind: Literal["tangle"] = "tangle"
        child: Annotated[Union[_PlainLeaf, _Tangle], PydanticField(discriminator="kind")] | None = None

    _Tangle.model_rebuild()
    assert _refusals(_Tangle, {"child": {"kind": "twig"}})[0][:2] == (("child",), "union_tag_invalid")
    tangle = _Tangle.model_validate({"child": {"kind": "plain", "at": NAIVE}})
    assert isinstance(tangle.child, _PlainLeaf) and tangle.child.at.tzinfo is None


def test_a_plain_model_around_the_same_type_stays_as_it_was() -> None:
    class _PlainParent(BaseModel):
        span: _Span

    assert _PlainParent.model_validate({"span": {"start": NAIVE}}).span.start.tzinfo is None


def test_a_hook_taken_from_a_base_ahead_of_base_schema_is_refused_when_defined() -> None:
    """A metaclass sees the class's own resolution: a mixin listed ahead of BaseSchema would
    supply the hook. One listed behind it supplies nothing BaseSchema does not already."""

    class _Mixin:
        @classmethod
        def __get_pydantic_core_schema__(cls, source: Any, handler: GetCoreSchemaHandler) -> CoreSchema:
            return handler(source)

    with pytest.raises(TypeError, match=r"takes __get_pydantic_core_schema__ from .*_Mixin"):

        class _Body(_Mixin, BaseSchema):
            at: datetime

    class _Behind(BaseSchema, _Mixin):
        at: datetime

    assert _refusals(_Behind, {"at": NAIVE})[0][1] == "timestamp_offset_required"


def test_a_class_between_that_defines_a_hook_is_refused_when_defined() -> None:
    with pytest.raises(TypeError, match="defines __pydantic_init_subclass__"):

        class _Quiet(BaseSchema):
            @classmethod
            def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
                return None


def test_an_init_of_its_own_is_refused_when_defined_or_taken_from_ahead() -> None:
    """An __init__ reads what a caller passes before the schema validates it, so it could turn
    timestamp text without an offset into a value the refusal never sees."""
    with pytest.raises(TypeError, match="defines __init__"):

        class _Eager(BaseSchema):
            at: datetime

            def __init__(self, **data: Any) -> None:
                super().__init__(**data)

    class _Mixin:
        def __init__(self, **data: Any) -> None:
            super().__init__(**data)

    with pytest.raises(TypeError, match=r"takes __init__ from .*_Mixin.*model_validator"):

        class _Ahead(_Mixin, BaseSchema):
            at: datetime

    class _Behind(BaseSchema, _Mixin):  # Pydantic's own __init__ comes first, as on every schema
        at: datetime

    assert _refusals(_Behind, {"at": NAIVE})[0][1] == "timestamp_offset_required"


def test_nothing_a_caller_hands_the_validation_reaches_the_refusal() -> None:
    """The framework once trusted text under a validation context of its own, which any caller
    can pass. Its trust is a context variable now, and the refusal is handed the value alone,
    so a context reaches it under no name, the one the framework used included."""
    node = _ReminderPayload.__pydantic_core_schema__["schema"]["fields"]["remind_at"]["schema"]
    assert node["function"] == {"type": "no-info", "function": refuse_timestamp_text_without_offset}
    with pytest.raises(ValidationError, match="UTC offset"):
        _ReminderPayload.model_validate({"remind_at": NAIVE}, context={"terp.timestamps.server-text": True})


def test_the_frameworks_trust_ends_with_its_read() -> None:
    with _reading_server_text():
        assert _ReminderPayload.model_validate({"remind_at": NAIVE}).remind_at == datetime(2026, 11, 6, 10, 0)
    with pytest.raises(ValidationError, match="UTC offset"):
        _ReminderPayload.model_validate({"remind_at": NAIVE})


def test_a_lifted_refusal_spares_nothing_it_does_not_stand_in_front_of() -> None:
    """The refusal's node is the refusal in front of a timestamp. The same function declared in
    front of anything else is the app's own validator, and what it stands in front of is held."""

    class _Lifted(BaseSchema):
        mark: Annotated[_SpanDict, BeforeValidator(refuse_timestamp_text_without_offset)]

    assert _refusals(_Lifted, {"mark": {"start": NAIVE}})[0][:2] == (("mark", "start"), "timestamp_offset_required")
