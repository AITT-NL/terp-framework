"""Runtime layer of the response-boundary guards (ADR 0020 / ADR 0084).

``create_app`` refuses to boot when any mounted route violates a response-boundary
rule of the Terp Standard, scanning the **composed** route table (decorator routes,
imperative ``add_api_route`` registration, and nested, included routers):

* ``response_model_not_table_model`` -- a ``table=True`` ORM model (directly or
  wrapped in ``Page[...]`` / ``list[...]``) must never serialize out;
* ``routes_declare_response_model`` -- a content route declares a ``response_model``
  (no-body 204/205/304 statuses and ``Response``-returning non-content routes exempt);
* ``schemas_exclude_sensitive_fields`` -- a response DTO never exposes a
  credential-shaped field;
* ``list_routes_paginate`` -- a list route returns a capped ``Page[T]``, never a
  bare ``list[...]``;
* ``schemas_avoid_positional_tuples`` -- the generated OpenAPI document carries no
  positional array shape (``prefixItems``, or the list form of ``items``); this one
  validates the document itself after composition, not the annotations, so it judges
  the wire truth (variadic ``tuple[X, ...]`` passes; a tuple behind a discriminated
  union does not hide) and reports every offence in one boot.

Each is the fail-closed *runtime* half pairing with the same-named build-time
``terp.arch`` rule (``tests/architecture/test_arch_harness.py``); the mirrored
constants are parity-locked here so the two layers cannot drift.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Annotated, Literal

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.responses import StreamingResponse
from pydantic import Field as PydanticField
from sqlmodel import Field

from terp.core import BaseSchema, BaseTable, ModuleSpec, Page, Policy, create_app
from terp.core.app import BootError


class _Secret(BaseTable, table=True):
    """A persisted model carrying a column that must never be serialized out."""

    __tablename__ = "rmg_secret"

    hashed_password: str = Field(max_length=128)


class _SecretRead(BaseSchema):
    """The safe read DTO: it lists only non-sensitive fields."""

    id: uuid.UUID


def _spec(router: APIRouter) -> ModuleSpec:
    return ModuleSpec(name="rmg", router=router, policy=Policy.default())


def test_boot_rejects_table_model_wrapped_in_page() -> None:
    router = APIRouter()

    @router.get("/", response_model=Page[_Secret])
    def list_secrets() -> Page[_Secret]: ...

    with pytest.raises(BootError, match="_Secret"):
        create_app([_spec(router)])


def test_boot_rejects_a_bare_table_model() -> None:
    router = APIRouter()

    @router.get("/{secret_id}", response_model=_Secret)
    def get_secret(secret_id: uuid.UUID) -> _Secret: ...

    with pytest.raises(BootError, match="response_model"):
        create_app([_spec(router)])


def test_boot_rejects_a_table_model_in_a_list() -> None:
    router = APIRouter()

    @router.get("/", response_model=list[_Secret])
    def list_secrets() -> list[_Secret]: ...

    with pytest.raises(BootError, match="_Secret"):
        create_app([_spec(router)])


def test_boot_rejects_a_table_model_on_a_nested_router() -> None:
    # A route declared on an *included* sub-router must still be guarded -- FastAPI
    # keeps it as a nested _IncludedRouter, not a flat entry in router.routes.
    inner = APIRouter()

    @inner.get("/inner", response_model=_Secret)
    def inner_route() -> _Secret: ...

    outer = APIRouter()
    outer.include_router(inner, prefix="/sub")

    with pytest.raises(BootError, match="_Secret"):
        create_app([_spec(outer)])


def test_boot_accepts_a_read_dto() -> None:
    router = APIRouter()

    @router.get("/", response_model=Page[_SecretRead])
    def list_secrets() -> Page[_SecretRead]: ...

    @router.delete("/{secret_id}", status_code=204)
    def remove(secret_id: uuid.UUID) -> None: ...

    app = create_app([_spec(router)])
    assert isinstance(app, FastAPI)


# --------------------------------------------------------------------------- #
# routes_declare_response_model -- the boot half (ADR 0084 deferral closed)
# --------------------------------------------------------------------------- #
def test_boot_rejects_a_content_route_with_no_response_model() -> None:
    router = APIRouter()

    @router.get("/")
    def list_things():  # no response_model, no return annotation: a bare object out
        ...

    with pytest.raises(BootError, match="backend/routes_declare_response_model"):
        create_app([_spec(router)])


def test_boot_rejects_an_imperative_route_with_no_response_model() -> None:
    router = APIRouter()

    def handler():  # registered via add_api_route, not a decorator
        ...

    router.add_api_route("/things", handler, methods=["GET"])

    with pytest.raises(BootError, match="backend/routes_declare_response_model"):
        create_app([_spec(router)])


def test_boot_rejects_an_undeclared_route_on_a_nested_router() -> None:
    inner = APIRouter()

    @inner.get("/inner")
    def inner_route(): ...

    outer = APIRouter()
    outer.include_router(inner, prefix="/sub")

    with pytest.raises(BootError, match="backend/routes_declare_response_model"):
        create_app([_spec(outer)])


def test_boot_accepts_a_no_body_status_route() -> None:
    router = APIRouter()

    @router.post("/refresh", status_code=205)
    def reset() -> None: ...

    @router.delete("/{secret_id}", status_code=204)
    def remove(secret_id: uuid.UUID) -> None: ...

    assert isinstance(create_app([_spec(router)]), FastAPI)


def test_boot_accepts_a_non_content_response_returning_route() -> None:
    # A StreamingResponse-annotated endpoint (a binary download) has no model to
    # declare -- the runtime analogue of the governed arch-allow opt-out.
    router = APIRouter()

    @router.get("/{file_id}/content")
    def download(file_id: uuid.UUID) -> StreamingResponse: ...

    assert isinstance(create_app([_spec(router)]), FastAPI)


def test_unresolvable_return_hints_still_fail_closed() -> None:
    # An endpoint whose annotations cannot be resolved is treated as a content
    # route (fail closed), never silently exempted.
    router = APIRouter()

    def handler(): ...

    router.add_api_route("/things", handler, methods=["GET"])
    handler.__annotations__["return"] = "_NoSuchNameAnywhere"

    with pytest.raises(BootError, match="backend/routes_declare_response_model"):
        create_app([_spec(router)])


# --------------------------------------------------------------------------- #
# schemas_exclude_sensitive_fields -- the boot half (ADR 0084 deferral closed)
# --------------------------------------------------------------------------- #
class _LeakyRead(BaseSchema):
    """A hand-rolled Read DTO that copies the stored hash -- the gap this closes."""

    id: uuid.UUID
    hashed_password: str


class _CleanRead(BaseSchema):
    """Near misses: counters and metadata that must never be flagged."""

    id: uuid.UUID
    token_version: int
    version: int
    token_type: str
    sort_key: str


def test_boot_rejects_a_credential_shaped_response_field() -> None:
    router = APIRouter()

    @router.get("/{user_id}", response_model=_LeakyRead)
    def get_user(user_id: uuid.UUID) -> _LeakyRead: ...

    with pytest.raises(BootError, match="backend/schemas_exclude_sensitive_fields"):
        create_app([_spec(router)])


def test_boot_rejects_a_sensitive_field_nested_in_a_page_envelope() -> None:
    router = APIRouter()

    @router.get("/", response_model=Page[_LeakyRead])
    def list_users() -> Page[_LeakyRead]: ...

    with pytest.raises(BootError, match="hashed_password"):
        create_app([_spec(router)])


def test_boot_accepts_benign_near_miss_field_names() -> None:
    router = APIRouter()

    @router.get("/{user_id}", response_model=_CleanRead)
    def get_user(user_id: uuid.UUID) -> _CleanRead: ...

    assert isinstance(create_app([_spec(router)]), FastAPI)


def test_framework_vetted_dtos_are_exempt() -> None:
    # A terp.*-owned response DTO is policed by the framework's own gate (where the
    # auth capability's minted AccessToken carries its justified, budgeted marker) --
    # mounting it in an app must not refuse the boot.
    from terp.capabilities.auth.schemas import AccessToken

    router = APIRouter()

    @router.post("/login", response_model=AccessToken)
    def login() -> AccessToken: ...

    assert isinstance(create_app([_spec(router)]), FastAPI)


# --------------------------------------------------------------------------- #
# list_routes_paginate -- the boot half (ADR 0084 deferral closed)
# --------------------------------------------------------------------------- #
def test_boot_rejects_a_bare_list_response_model() -> None:
    router = APIRouter()

    @router.get("/", response_model=list[_SecretRead])
    def list_secrets() -> list[_SecretRead]: ...

    with pytest.raises(BootError, match="backend/list_routes_paginate"):
        create_app([_spec(router)])


def test_boot_rejects_a_bare_sequence_response_model() -> None:
    router = APIRouter()

    @router.get("/", response_model=Sequence[_SecretRead])
    def list_secrets() -> Sequence[_SecretRead]: ...

    with pytest.raises(BootError, match="backend/list_routes_paginate"):
        create_app([_spec(router)])


def test_boot_rejects_an_unparametrized_list_response_model() -> None:
    router = APIRouter()

    def handler(): ...

    router.add_api_route("/things", handler, methods=["GET"], response_model=list)

    with pytest.raises(BootError, match="backend/list_routes_paginate"):
        create_app([_spec(router)])


def test_boot_rejects_a_bare_list_on_a_nested_router() -> None:
    inner = APIRouter()

    @inner.get("/inner", response_model=list[_SecretRead])
    def inner_route() -> list[_SecretRead]: ...

    outer = APIRouter()
    outer.include_router(inner, prefix="/sub")

    with pytest.raises(BootError, match="backend/list_routes_paginate"):
        create_app([_spec(outer)])


def test_boot_accepts_a_paginated_page_response_model() -> None:
    router = APIRouter()

    @router.get("/", response_model=Page[_SecretRead])
    def list_secrets() -> Page[_SecretRead]: ...

    @router.get("/{secret_id}", response_model=_SecretRead)
    def get_secret(secret_id: uuid.UUID) -> _SecretRead: ...

    assert isinstance(create_app([_spec(router)]), FastAPI)


# --------------------------------------------------------------------------- #
# runtime <-> build-time parity: the mirrored constants cannot drift
# --------------------------------------------------------------------------- #
def test_runtime_constants_match_the_arch_harness() -> None:
    """``terp.core`` (layer 0) cannot import ``terp.arch``, so the runtime checks
    mirror the harness's rule constants; this lock keeps the two layers identical."""
    from terp.arch.rules import _support as arch_support
    from terp.arch.rules import http as arch_http

    from terp.core import app as core_app

    assert core_app._NO_BODY_STATUS_CODES == arch_http._NO_BODY_STATUS_CODES
    assert core_app._SENSITIVE_FIELD_RE.pattern == arch_support._SENSITIVE_FIELD_RE.pattern
    assert core_app._SENSITIVE_FIELD_EXCLUSIONS == arch_support._SENSITIVE_FIELD_EXCLUSIONS
    # The harness matches collection annotations by *name*; the runtime check matches
    # the classes those names normalize to through ``get_origin`` (typing aliases
    # ``List`` / ``Sequence`` / ``Iterable`` / ``Collection`` resolve to the same
    # builtins / ABCs), so the name sets must correspond exactly.
    runtime_names = {tp.__name__ for tp in core_app._UNPAGINATED_COLLECTION_TYPES}
    assert runtime_names | {"List"} == set(arch_http._COLLECTION_RESPONSE_TYPES)


# --------------------------------------------------------------------------- #
# schemas_avoid_positional_tuples -- the boot half
# --------------------------------------------------------------------------- #
class _TupleRead(BaseSchema):
    """A Read DTO whose coordinate pair crosses the wire positionally."""

    id: uuid.UUID
    coordinates: tuple[float, float]


class _TupleCreate(BaseSchema):
    """The same shape on the way in, nested inside a container."""

    tags: list[tuple[str, str]]


class _NamedPoint(BaseSchema):
    lat: float
    lon: float


class _NamedRead(BaseSchema):
    """The compliant spelling: named fields, and a homogeneous list."""

    id: uuid.UUID
    coordinates: _NamedPoint
    tag_names: list[str]


def test_boot_rejects_a_tuple_typed_response_field() -> None:
    router = APIRouter()

    @router.get("/{thing_id}", response_model=_TupleRead)
    def get_thing(thing_id: uuid.UUID) -> _TupleRead: ...

    with pytest.raises(BootError, match="backend/schemas_avoid_positional_tuples"):
        create_app([_spec(router)])


def test_boot_rejects_a_tuple_arriving_through_the_request_body() -> None:
    # The request half of the same contract: a generated client has to construct the
    # body type too, so a tuple there is the identical failure one direction earlier.
    router = APIRouter()

    @router.post("/", response_model=_NamedRead)
    def create_thing(body: _TupleCreate) -> _NamedRead: ...

    with pytest.raises(BootError, match="coordinates|tags"):
        create_app([_spec(router)])


def test_boot_accepts_named_fields_and_homogeneous_lists() -> None:
    router = APIRouter()

    @router.get("/{thing_id}", response_model=_NamedRead)
    def get_thing(thing_id: uuid.UUID) -> _NamedRead: ...

    assert isinstance(create_app([_spec(router)]), FastAPI)


class _JoinStage(BaseSchema):
    """The member that hides the positional shape behind a discriminator."""

    kind: Literal["join"] = "join"
    on: tuple[str, str]


class _FilterStage(BaseSchema):
    kind: Literal["filter"] = "filter"
    field: str


class _PipelineRead(BaseSchema):
    stages: list[Annotated[_JoinStage | _FilterStage, PydanticField(discriminator="kind")]]


def test_boot_rejects_a_tuple_hiding_behind_a_discriminated_union() -> None:
    """The vector that blinded this check's earlier annotation walk.

    A union is not ``isinstance(_, type)``, so a walk over model annotations
    stopped dead at it and the ``prefixItems`` inside the member — the literal
    shape the rule is named after — sailed through. The document check cannot be
    blinded: however a type reaches the contract, its schema is in the document.
    """
    router = APIRouter()

    @router.get("/", response_model=_PipelineRead)
    def get_pipeline() -> _PipelineRead: ...

    with pytest.raises(BootError, match="_JoinStage"):
        create_app([_spec(router)])


class _FingerprintRead(BaseSchema):
    """The immutable spelling of a homogeneous sequence — compliant."""

    id: uuid.UUID
    fingerprint: tuple[str, ...]


def test_boot_accepts_a_variadic_tuple() -> None:
    """``tuple[X, ...]`` emits byte-identical schema to ``list[X]``: nothing
    positional reaches the wire, so refusing it forces a source rewrite with
    provably zero wire effect while the message asserts something false."""
    router = APIRouter()

    @router.get("/{thing_id}", response_model=_FingerprintRead)
    def get_thing(thing_id: uuid.UUID) -> _FingerprintRead: ...

    assert isinstance(create_app([_spec(router)]), FastAPI)


def test_boot_reports_every_positional_shape_in_one_error() -> None:
    """Raise-on-first hands the author fix-one-reboot-repeat, once per offending
    field; the gate must price the whole cleanup in a single boot."""
    router = APIRouter()

    @router.get("/a", response_model=_TupleRead)
    def get_a() -> _TupleRead: ...

    @router.post("/b", response_model=_NamedRead)
    def create_b(body: _TupleCreate) -> _NamedRead: ...

    with pytest.raises(BootError) as excinfo:
        create_app([_spec(router)])
    message = str(excinfo.value)
    assert "coordinates" in message
    assert "tags" in message
    assert "backend/schemas_avoid_positional_tuples" in message
