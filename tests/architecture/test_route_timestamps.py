"""ADR 0208: the app refuses to start while a route reads a timestamp nothing holds to its offset.

A ``BaseSchema`` puts the refusal of timestamp text without a UTC offset in front of every
timestamp it reads itself (ADR 0206). A route parameter, and a class that reads its own fields,
is read by nothing of the kind, so ``create_app`` walks the schema each parameter of each route
is read with and refuses every timestamp it finds with nothing in front of it. ``Instant`` is
the type that puts the refusal there.
"""

from __future__ import annotations

import dataclasses
import secrets
import uuid
from datetime import UTC, date, datetime
from typing import Annotated, Literal, TypedDict

import pytest
from fastapi import APIRouter, Body, Cookie, Depends, FastAPI, Header, Path, Query, WebSocket
from fastapi.testclient import TestClient
from starlette.requests import HTTPConnection
from pydantic import (
    AwareDatetime,
    BaseModel,
    Field,
    NaiveDatetime,
    PastDatetime,
    PlainValidator,
    TypeAdapter,
    ValidationError,
    computed_field,
)
from pydantic.dataclasses import dataclass as pydantic_dataclass

from terp.core import (
    EDITOR,
    BaseSchema,
    BootError,
    Instant,
    LocalTimeIn,
    ModuleSpec,
    NaiveMeansUtc,
    Policy,
    Principal,
    create_app,
)
from terp.core.route_timestamps import _findings, request_timestamps_refusal
from terp.core.timestamps import OFFSET_REQUIRED, refuse_timestamp_text_without_offset

NAIVE = "2026-11-06T10:00:00"
AWARE = "2026-11-06T10:00:00+01:00"


def _found(app: FastAPI) -> list[str]:
    return list(_findings(app.routes))


# --------------------------------------------------------------------------- #
# Instant: the refusal as a type
# --------------------------------------------------------------------------- #


def test_instant_refuses_text_without_its_offset_and_reads_the_rest_as_a_datetime() -> None:
    instant = TypeAdapter(Instant)
    with pytest.raises(ValidationError) as caught:
        instant.validate_python(NAIVE)
    (error,) = caught.value.errors()
    assert (error["type"], error["msg"]) == ("timestamp_offset_required", OFFSET_REQUIRED)
    assert instant.validate_python(AWARE) == datetime(2026, 11, 6, 9, 0, tzinfo=UTC)
    assert instant.validate_python(datetime(2026, 11, 6, 10, 0)) == datetime(2026, 11, 6, 10, 0)
    assert instant.validate_python(0) == datetime(1970, 1, 1, tzinfo=UTC)
    with pytest.raises(ValidationError) as caught:
        instant.validate_python("next tuesday")
    assert caught.value.errors()[0]["type"] == "datetime_from_date_parsing"


def test_instant_publishes_a_datetimes_contract() -> None:
    assert TypeAdapter(Instant).json_schema() == TypeAdapter(datetime).json_schema()


class _Stamped(BaseSchema):
    at: Instant
    other: datetime


def test_in_a_base_schema_instant_is_the_schemas_own_refusal_once() -> None:
    fields = _Stamped.__pydantic_core_schema__["schema"]["fields"]
    for name in ("at", "other"):
        node = fields[name]["schema"]
        assert node["type"] == "function-before"
        assert node["function"]["function"] is refuse_timestamp_text_without_offset
        assert node["schema"]["type"] == "datetime"


def test_instant_names_itself() -> None:
    assert repr(Instant.__metadata__[0]) == "Instant"


# --------------------------------------------------------------------------- #
# what the walk refuses
# --------------------------------------------------------------------------- #


class _Window(BaseModel):
    opens_at: datetime
    closes_at: Instant


def _since(since: datetime | None = None) -> datetime | None:
    return since


class _Filters:
    def __init__(self, after: datetime | None = None, before: Instant | None = None) -> None:
        self.after = after


def test_a_plain_timestamp_parameter_is_refused_wherever_fastapi_reads_it() -> None:
    app = FastAPI()

    @app.get("/stamps/{at}")
    def by_path(
        at: datetime = Path(),
        since: datetime | None = Query(None, alias="from"),
        sent_at: datetime | None = Header(None),
        seen_at: datetime | None = Cookie(None),
        naive: NaiveDatetime | None = None,
        past: PastDatetime | None = None,
        _since: datetime | None = Depends(_since),
        filters: _Filters = Depends(),
    ) -> dict[str, str]:
        return {}

    @app.websocket("/live")
    async def live(websocket: WebSocket, since: datetime | None = None) -> None:
        await websocket.close()

    assert sorted(_found(app)) == sorted(
        [
            "GET /stamps/{at} reads a timestamp in the path parameter 'at'",
            "GET /stamps/{at} reads a timestamp in the query parameter 'from'",
            "GET /stamps/{at} reads a timestamp in the header 'sent-at'",
            "GET /stamps/{at} reads a timestamp in the cookie 'seen_at'",
            "GET /stamps/{at} reads a timestamp in the query parameter 'naive'",
            "GET /stamps/{at} reads a timestamp in the query parameter 'past'",
            "GET /stamps/{at} reads a timestamp in the query parameter 'since'",
            "GET /stamps/{at} reads a timestamp in the query parameter 'after'",
            "WebSocket /live reads a timestamp in the query parameter 'since'",
        ]
    )


def test_a_route_is_read_as_it_is_served_under_every_router_that_includes_it() -> None:
    # Its path carries every prefix, and the dependencies an include adds are read too.
    inner = APIRouter()

    @inner.get("/deep")
    def deep(until: Instant | None = None) -> dict[str, str]:
        return {}

    module = APIRouter()
    module.include_router(inner, prefix="/inner")
    app = FastAPI()
    app.include_router(module, prefix="/api/v1/events", dependencies=[Depends(_since)])

    assert _found(app) == [
        "GET /api/v1/events/inner/deep reads a timestamp in the query parameter 'since'"
    ]


@pydantic_dataclass
class _Slot:
    begins: datetime


class _Booking(BaseModel):
    starts_at: datetime
    day: date

    @computed_field  # type: ignore[prop-decorator]
    @property
    def shown_at(self) -> datetime:  # written only, never read from a request
        return self.starts_at


class _Held(BaseSchema):
    starts_at: datetime
    window: _Window
    also: _Window | None = None


class _Cat(BaseModel):
    kind: Literal["cat"]
    fed_at: datetime


class _Dog(BaseModel):
    kind: Literal["dog"]
    walked_at: datetime


class _Tree(BaseModel):
    planted_at: datetime
    branches: list[_Tree] = []


class _QueryModel(BaseModel):
    since: datetime | None = None


class _Kennel(BaseModel):
    pet: _Cat | _Dog = Field(discriminator="kind")


def test_a_body_that_is_or_nests_a_class_reading_its_own_fields_is_refused() -> None:
    app = FastAPI()

    @app.post("/bookings")
    def booking(booking: _Booking) -> dict[str, str]:
        return {}

    @app.post("/held")
    def held(held: _Held) -> dict[str, str]:
        return {}

    @app.post("/many")
    def many(
        slots: list[_Slot],
        pet: Annotated[_Cat | _Dog, Field(discriminator="kind")],
        tree: _Tree,
        stamps: dict[str, datetime] = Body(),
        pair: tuple[datetime, datetime] = Body(),
    ) -> dict[str, str]:
        return {}

    @app.get("/query-model")
    def query_model(query: Annotated[_QueryModel, Query()]) -> dict[str, str]:
        return {}

    @app.post("/kennel")
    def kennel(kennel: _Kennel) -> dict[str, str]:
        return {}

    assert sorted(_found(app)) == sorted(
        [
            "POST /bookings reads a timestamp in the body field 'booking', in _Booking.starts_at",
            "POST /held reads a timestamp in the body field 'held', in _Window.opens_at",
            "POST /many reads a timestamp in the body field 'slots', in _Slot.begins",
            "POST /many reads a timestamp in the body field 'pet', in _Cat.fed_at",
            "POST /many reads a timestamp in the body field 'pet', in _Dog.walked_at",
            "POST /many reads a timestamp in the body field 'tree', in _Tree.planted_at",
            "POST /many reads a timestamp in the body field 'stamps'",
            "POST /many reads a timestamp in the body field 'pair'",
            "GET /query-model reads a timestamp in the query parameter 'query', in _QueryModel.since",
            "POST /kennel reads a timestamp in the body field 'kennel', in _Cat.fed_at",
            "POST /kennel reads a timestamp in the body field 'kennel', in _Dog.walked_at",
        ]
    )


# --------------------------------------------------------------------------- #
# what the walk leaves
# --------------------------------------------------------------------------- #


@dataclasses.dataclass
class _StdSlot:
    begins: datetime


class _Times(TypedDict):
    when: datetime


class _Inner(BaseSchema):
    at: datetime


class _AllHeld(BaseSchema):
    slot: _StdSlot
    times: _Times
    inner: _Inner
    inners: list[_Inner]


class _QuerySchema(BaseSchema):
    since: datetime | None = None


def test_what_holds_its_offset_passes() -> None:
    app = FastAPI()

    @app.get("/params")
    def params(
        until: Instant,
        maybe: Instant | None = None,
        named: Annotated[Instant | None, Query(alias="from")] = None,
        local: Annotated[datetime, LocalTimeIn("Europe/Amsterdam")] | None = None,
        utc: NaiveMeansUtc | None = None,
        aware: AwareDatetime | None = None,
        day: date | None = None,
        count: int = 0,
        query: Annotated[_QuerySchema, Query()] = None,  # type: ignore[assignment]
    ) -> dict[str, str]:
        return {}

    @app.post("/held", response_model=_Booking)
    def held(held: _AllHeld, window: _Window | None = None) -> _Booking:
        raise NotImplementedError

    assert _found(app) == ["POST /held reads a timestamp in the body field 'window', in _Window.opens_at"]


def test_a_response_model_and_a_computed_field_are_never_read_from_a_request() -> None:
    class _Written(BaseModel):
        day: date

        @computed_field  # type: ignore[prop-decorator]
        @property
        def at(self) -> datetime:
            return datetime(2026, 11, 6, tzinfo=UTC)

    app = FastAPI()

    @app.post("/written", response_model=_Booking)
    def written(body: _Written) -> _Booking:
        raise NotImplementedError

    assert _found(app) == []


def test_a_plain_validator_leaves_no_timestamp_for_the_walk_to_see() -> None:
    # It replaces the type entirely: an app's own early validator, which the build-time rule
    # counts (ADR 0207). The walk sees no timestamp, so it is not the walk's to refuse.
    app = FastAPI()

    @app.get("/plain")
    def plain(at: Annotated[datetime, PlainValidator(datetime.fromisoformat)]) -> dict[str, str]:
        return {}

    assert _found(app) == []


# --------------------------------------------------------------------------- #
# the refusal, and create_app
# --------------------------------------------------------------------------- #


def test_the_refusal_names_every_finding_once_and_the_fix() -> None:
    app = FastAPI()

    @app.get("/one")
    def one(since: datetime) -> dict[str, str]:
        return {}

    @app.get("/two")
    def two(since: datetime, _since: datetime | None = Depends(_since)) -> dict[str, str]:
        return {}

    refusal = request_timestamps_refusal(app.routes)
    assert refusal is not None
    assert refusal.count("GET /one reads a timestamp in the query parameter 'since'") == 1
    assert refusal.count("GET /two reads a timestamp in the query parameter 'since'") == 1
    for fix in ("Instant, from terp.core", "LocalTimeIn('<zone>')", "NaiveMeansUtc", "BaseSchema", "ADR 0208"):
        assert fix in refusal
    assert request_timestamps_refusal(FastAPI().routes) is None


_TOKEN = "tok-" + secrets.token_hex(6)
_AUTH = {"Authorization": f"Bearer {_TOKEN}"}


def _principal(connection: HTTPConnection) -> Principal | None:
    if connection.headers.get("authorization") == f"Bearer {_TOKEN}":
        return Principal(id=uuid.UUID(int=7), role=EDITOR)
    return None


def test_create_app_refuses_to_start_while_a_route_reads_a_plain_timestamp() -> None:
    router = APIRouter()

    @router.get("/")
    def since(after: datetime | None = None) -> dict[str, str]:
        return {}

    with pytest.raises(BootError) as caught:
        create_app(
            [ModuleSpec(name="events", router=router, policy=Policy.default())],
            principal_provider=_principal,
        )
    assert "GET /api/v1/events/ reads a timestamp in the query parameter 'after'" in str(caught.value)


def test_with_every_timestamp_held_the_app_starts_and_refuses_one_without_its_offset() -> None:
    router = APIRouter()

    @router.get("/", response_model=dict[str, str])
    def since(after: Instant | None = None) -> dict[str, str]:
        return {"after": after.isoformat() if after else ""}

    app = create_app(
        [ModuleSpec(name="events", router=router, policy=Policy.default())],
        principal_provider=_principal,
    )
    client = TestClient(app)
    refused = client.get("/api/v1/events/", params={"after": NAIVE}, headers=_AUTH)
    assert refused.status_code == 422
    (detail,) = refused.json()["detail"]
    assert (detail["loc"], detail["type"]) == (["query", "after"], "timestamp_offset_required")
    taken = client.get("/api/v1/events/", params={"after": AWARE}, headers=_AUTH)
    assert (taken.status_code, taken.json()) == (200, {"after": AWARE})
