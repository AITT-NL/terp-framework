"""A field declared personal never reaches the log, the audit trail or a public payload (ADR 0190).

``Personal`` is ``Field`` with one fact added, and every test here holds one reader of that
fact to what the record promises:

* **the declaration** -- it lands in the field's metadata (every model, every subclass) and
  in the column's ``info`` (database metadata alone), and changes no DDL;
* **rendering** -- a Terp model renders ``[PERSONAL]`` for each declared field wherever it
  is rendered, and so does any other pydantic model the log is handed;
* **the log** -- each path a value can take into a record: an argument, the message, a
  mapping argument, ``extra=``, ``log_context`` on an ``AppError``, an unexpected
  exception's text, a validation error's text, a database's refusal, and the access line;
* **the audit trail** -- a payload keeps the key and loses the value;
* **events and jobs** -- a ``PUBLIC`` payload cannot declare a personal field, and
  ``redact_personal`` is the copy that may leave the process.

The personal values are generated per run (ADR 0163): a literal address in a test is a
real-looking address in the history.
"""

from __future__ import annotations

import contextlib
import datetime
import io
import json
import logging
import secrets
import uuid
from collections.abc import Iterator
from typing import Annotated, Any

import pytest
from fastapi import APIRouter, FastAPI
from jsonschema import Draft202012Validator
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import Column, MetaData, String, Table
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import CreateTable
from sqlmodel import JSON, Field, Session, SQLModel, create_engine
from starlette.requests import HTTPConnection

from terp.core import (
    EDITOR,
    PERSONAL,
    AuditAction,
    AuditPolicy,
    BaseSchema,
    BaseService,
    BaseTable,
    BaseUpdateSchema,
    ConflictError,
    EventDefinition,
    EventVisibility,
    ModuleSpec,
    NotFoundError,
    Personal,
    Policy,
    Principal,
    create_app,
    log_record_schema,
    personal_columns,
    personal_field_names,
    personal_fields,
    redact_personal,
)
from terp.core._redaction import LoggedModel
from terp.core.logging import RedactingFilter, StructuredFormatter, _protect_handler
from terp.core.audit import emit_audit
from terp.core.base_service import _integrity_detail
from terp.core.jobs import JobDefinition, JobVisibility
from terp.core.personal import MaskedModel, is_personal_name, withhold_personal_values

_EMAIL = f"p-{secrets.token_hex(5)}@example.test"
_OTHER_EMAIL = f"q-{secrets.token_hex(5)}@example.test"
_PHONE = "+31 6 " + "".join(str(secrets.randbelow(10)) for _ in range(8))
_BORN = datetime.date(1940 + secrets.randbelow(60), 1 + secrets.randbelow(12), 1 + secrets.randbelow(28))
_TOKEN = "tok-" + secrets.token_hex(6)
_PERSONAL_VALUES = (_EMAIL, _OTHER_EMAIL, _PHONE, _BORN.isoformat())


# The record helpers, kept here rather than imported from the structured-log suite: importing a
# test module by a second name defines its classes twice.
_VALIDATOR = Draft202012Validator(log_record_schema())


def assert_record(line: dict[str, Any]) -> None:
    """*line* validates against the ``terp-log/1`` schema."""
    errors = sorted(error.message for error in _VALIDATOR.iter_errors(line))
    assert errors == [], f"{line!r} breaks terp-log/1: {errors}"


@contextlib.contextmanager
def captured() -> Iterator[list[dict[str, Any]]]:
    """Collect every record the root logger sees, as parsed lines."""
    stream = io.StringIO()
    handler = _protect_handler(logging.StreamHandler(stream))
    handler.setLevel(logging.DEBUG)
    root = logging.getLogger()
    root.addHandler(handler)
    lines: list[dict[str, Any]] = []
    try:
        yield lines
    finally:
        root.removeHandler(handler)
        lines.extend(json.loads(text) for text in stream.getvalue().splitlines())


def _record(msg: object = "m", args: Any = None, **attrs: Any) -> logging.LogRecord:
    record = logging.LogRecord("probe", logging.INFO, "p", 1, msg, args, None)
    for key, value in attrs.items():
        setattr(record, key, value)
    return record


def _render(record: logging.LogRecord) -> dict[str, Any]:
    RedactingFilter().filter(record)
    return json.loads(StructuredFormatter().format(record))


class _Customer(BaseTable, table=True):
    __tablename__ = "pii_probe_customer"
    email: str = Personal(max_length=320, index=True, unique=True)
    phone: str | None = Personal(default=None, max_length=32)
    date_of_birth: datetime.date | None = Personal(default=None)
    note: str = Field(default="", max_length=200)
    extra_data: dict[str, Any] = Field(default_factory=dict, sa_type=JSON)


class _CustomerCreate(BaseSchema):
    email: str = Personal(max_length=320)
    phone: str | None = Personal(default=None, max_length=32)


class _Tag(BaseSchema):
    label: str = Field(max_length=40)
    owner_email: str = Personal(max_length=320)


class _CustomerRead(BaseSchema):
    id: uuid.UUID
    email: str = Personal()
    note: str = ""
    tags: list[_Tag] = Field(default_factory=list)


class _Contact(SQLModel):
    """A plain model: no Terp base, so it is masked when logged but not self-masking."""

    email: str = Personal()
    city: str = ""


class _Strict(BaseSchema):
    email: str = Personal(max_length=8)


class _Envelope(BaseSchema):
    """A payload that carries a model as one of its fields."""

    customer: _CustomerRead
    label: str = ""


class _City(BaseSchema):
    city: str = Field(default="", max_length=80)


class _Customers(BaseService[_Customer, _CustomerCreate, BaseUpdateSchema]):
    model = _Customer


def _read() -> _CustomerRead:
    return _CustomerRead(
        id=uuid.uuid4(), email=_EMAIL, note="vip", tags=[_Tag(label="lead", owner_email=_OTHER_EMAIL)]
    )


def _served(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The lines the app wrote: the test client logs its own requests, URL and all."""
    return [line for line in lines if not line["logger"].startswith("httpx")]


def _no_personal_value_in(text: str) -> None:
    for value in _PERSONAL_VALUES:
        assert value not in text, f"{value!r} reached {text[:400]!r}"


# --------------------------------------------------------------------------- #
# the declaration
# --------------------------------------------------------------------------- #
def test_the_declaration_is_on_the_field_and_on_the_column() -> None:
    assert personal_fields(_Customer) == {"email", "phone", "date_of_birth"}
    assert personal_fields(_Customer(email=_EMAIL)) == personal_fields(_Customer)
    assert personal_fields(_CustomerRead) == {"email"}
    assert personal_fields(_Contact) == {"email"}
    columns = _Customer.__table__.c  # type: ignore[attr-defined]
    assert columns.email.info == {"terp_personal": True}
    assert columns.email.unique and columns.email.index  # Field's keywords all arrive
    assert "terp_personal" not in columns.note.info
    assert personal_columns()["pii_probe_customer"] == ("email", "phone", "date_of_birth")
    # Not a model at all: nothing is declared.
    assert personal_fields(int) == frozenset()


def test_the_declaration_changes_no_ddl_and_no_api_contract() -> None:
    class _Declared(SQLModel, table=True):
        __tablename__ = "pii_ddl_declared"
        id: int | None = Field(default=None, primary_key=True)
        email: str = Personal(max_length=320, unique=True)

    class _Undeclared(SQLModel, table=True):
        __tablename__ = "pii_ddl_undeclared"
        id: int | None = Field(default=None, primary_key=True)
        email: str = Field(max_length=320, unique=True)

    with_marker = str(CreateTable(_Declared.__table__)).replace("pii_ddl_declared", "t")  # type: ignore[attr-defined]
    without = str(CreateTable(_Undeclared.__table__)).replace("pii_ddl_undeclared", "t")  # type: ignore[attr-defined]
    assert with_marker == without
    # The marker never reaches a JSON schema, so the OpenAPI document is unchanged.
    assert "terp" not in json.dumps(_CustomerRead.model_json_schema()).lower()


def test_a_hand_built_column_and_extra_column_keywords_are_marked_in_place() -> None:
    class _Built(SQLModel, table=True):
        __tablename__ = "pii_built"
        id: int | None = Field(default=None, primary_key=True)
        nick: str = Personal("x", sa_column=Column(String(20)))
        alias: str = Personal(
            default="", max_length=20, sa_column_kwargs={"comment": "kept", "info": {"k": 1}}
        )

    columns = _Built.__table__.c  # type: ignore[attr-defined]
    assert columns.nick.info == {"terp_personal": True}
    assert columns.alias.info == {"k": 1, "terp_personal": True}
    assert columns.alias.comment == "kept"
    assert _Built().nick == "x"  # the positional default is Field's default
    found = personal_columns(_Built.metadata)
    assert found["pii_built"] == ("nick", "alias")
    empty = MetaData()
    Table("pii_nothing", empty, Column("email", String(10)))
    assert personal_columns(empty) == {}


def test_a_subclass_keeps_the_declaration_and_a_redeclaration_drops_it() -> None:
    class _Kept(_CustomerRead):
        pass

    class _Dropped(_CustomerRead):
        email: str = ""

    assert personal_fields(_Kept) == {"email"}
    assert personal_fields(_Dropped) == frozenset()


def test_the_annotated_spelling_is_read_too() -> None:
    # Not taught, but read the same way: the rule accepts it, so the runtime must too.
    class _Annotated(BaseSchema):
        contact_email: Annotated[str, Personal(max_length=320)] = ""

    assert personal_fields(_Annotated) == {"contact_email"}


def test_the_names_are_collected_from_terp_models_only() -> None:
    assert {"email", "phone", "date_of_birth", "owner_email"} <= personal_field_names()
    assert is_personal_name("EMAIL") and not is_personal_name("note")

    class _Unregistered(SQLModel):
        unregistered_probe_marker: str = Personal(default="")

    # A plain model is masked when rendered, but its names are not collected.
    assert personal_fields(_Unregistered) == {"unregistered_probe_marker"}
    assert "unregistered_probe_marker" not in personal_field_names()


def test_a_personal_model_hides_its_input_in_a_validation_error() -> None:
    with pytest.raises(ValidationError) as refused:
        _Strict(email=_EMAIL)
    _no_personal_value_in(str(refused.value))
    # The structured form keeps it: that is what a 422 is built from, for its own caller.
    assert refused.value.errors()[0]["input"] == _EMAIL

    class _Plain(BaseSchema):
        code: str = Field(max_length=2)

    with pytest.raises(ValidationError) as plain:
        _Plain(code="toolong")
    assert "toolong" in str(plain.value)  # a model with nothing personal is unchanged

    class _Explicit(BaseSchema):
        model_config = ConfigDict(hide_input_in_errors=True)
        email: str = Personal(max_length=8)

    class _Overridden(BaseSchema):
        model_config = ConfigDict(hide_input_in_errors=False)
        email: str = Personal(max_length=8)

    for model in (_Explicit, _Overridden):
        with pytest.raises(ValidationError) as hidden:
            model(email=_EMAIL)
        _no_personal_value_in(str(hidden.value))


def test_a_forward_reference_is_resolved_and_still_hides_its_input() -> None:
    class _Later(BaseSchema):
        email: str = Personal(max_length=8)
        child: _Missing | None = None  # noqa: F821 - defined below, on purpose

    class _Missing(BaseSchema):
        code: str = ""

    _Later.model_rebuild(_types_namespace={"_Missing": _Missing})
    with pytest.raises(ValidationError) as refused:
        _Later(email=_EMAIL)
    _no_personal_value_in(str(refused.value))


def test_a_422_still_shows_the_caller_what_it_sent() -> None:
    router = APIRouter()

    @router.post("/strict")
    def strict(body: _Strict) -> dict[str, str]:
        return {}

    client = TestClient(_compose(router))
    with captured() as lines:
        response = client.post("/api/v1/pii/strict", json={"email": _EMAIL}, headers=_AUTH)
    assert response.status_code == 422
    assert response.json()["detail"][0]["input"] == _EMAIL
    _no_personal_value_in(json.dumps(_served(lines)))


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #
def test_a_terp_model_renders_its_personal_fields_withheld() -> None:
    row = _Customer(email=_EMAIL, phone=_PHONE, date_of_birth=_BORN, note="vip",
                    extra_data={"email": _OTHER_EMAIL, "kind": "lead"})
    read = _read()
    for rendered in (repr(row), str(row), f"{row}", repr(read), str(read), f"{read!r}"):
        _no_personal_value_in(rendered)
        assert PERSONAL in rendered
    assert "note='vip'" in repr(row) and "'kind': 'lead'" in repr(row)
    assert "email=[PERSONAL]" in repr(read)
    assert "owner_email=[PERSONAL]" in repr(read)  # a nested model in a list


def test_any_pydantic_model_renders_masked_through_the_log() -> None:
    contact = _Contact(email=_EMAIL, city="Delft")
    assert _EMAIL in repr(contact)  # a plain model does not mask itself ...
    for rendered in (repr(MaskedModel(contact)), str(MaskedModel(contact))):
        _no_personal_value_in(rendered)  # ... the log's rendering of it does
        assert "city='Delft'" in rendered

    class _Wrapped(BaseModel):
        contact: _Contact
        pair: tuple[_Contact, ...]
        by_name: dict[str, str]

    wrapped = _Wrapped(contact=contact, pair=(contact,), by_name={"email": _EMAIL})
    _no_personal_value_in(repr(MaskedModel(wrapped)))

    class _Credentialed(BaseModel):
        password: str

    _no_personal_value_in(str(LoggedModel(_Contact(email=_EMAIL))))
    assert _TOKEN not in str(LoggedModel(_Credentialed(password=_TOKEN)))
    assert _TOKEN not in repr(LoggedModel(_Credentialed(password=_TOKEN)))


# --------------------------------------------------------------------------- #
# the log, path by path
# --------------------------------------------------------------------------- #
def test_a_record_withholds_every_declared_value_it_was_handed() -> None:
    read, contact = _read(), _Contact(email=_EMAIL, city="Delft")
    lines = [
        _render(_record("read %s", (read,))),
        _render(_record("read %r", (read,))),
        _render(_record("plain %s", (contact,))),
        _render(_record(read)),
        _render(_record(contact)),
        _render(_record("%(email)s and %(note)s", {"email": _EMAIL, "note": "kept"})),
        _render(_record("x", None, email=_EMAIL, customer=read, nested={"phone": _PHONE})),
        _render(_record("x", None, contacts=[contact], pair=(contact,), plain=7)),
    ]
    for line in lines:
        assert_record(line)
        _no_personal_value_in(json.dumps(line))
    assert lines[4]["message"] == f"email={PERSONAL} city='Delft'"
    assert lines[5]["message"] == f"{PERSONAL} and kept"
    assert lines[6]["extra"]["email"] == PERSONAL
    assert lines[6]["extra"]["nested"] == {"phone": PERSONAL}
    assert "email=[PERSONAL]" in lines[6]["extra"]["customer"]
    assert lines[7]["extra"]["plain"] == 7
    # A secret keeps its own mark beside a personal one.
    secret = _render(_record("x", None, auth={"token": _TOKEN, "email": _EMAIL}))
    assert secret["extra"]["auth"] == {"token": "[REDACTED]", "email": PERSONAL}


def test_a_bare_value_is_not_a_field() -> None:
    # The documented boundary: an address passed on its own has no declaration behind it.
    line = _render(_record("invited %s", (_EMAIL,)))
    assert line["message"] == f"invited {_EMAIL}"


_ACTOR = uuid.UUID("0b6c1f4e-2a3d-4e5f-9a8b-7c6d5e4f3a2b")
_AUTH = {"Authorization": f"Bearer {_TOKEN}"}


def _principal(connection: HTTPConnection) -> Principal | None:
    if connection.headers.get("authorization") == f"Bearer {_TOKEN}":
        return Principal(id=_ACTOR, role=EDITOR)
    return None


def _compose(router: APIRouter) -> FastAPI:
    return create_app(
        [ModuleSpec(name="pii", router=router, policy=Policy.default())],
        principal_provider=_principal,
    )


def _app() -> FastAPI:
    router = APIRouter()
    log = logging.getLogger("pii.probe")

    @router.get("/customers/{customer_id}")
    def read(customer_id: uuid.UUID, email: str = "") -> dict[str, str]:
        return {"id": str(customer_id)}

    @router.get("/by-name")
    def by_name() -> dict[str, str]:
        raise NotFoundError(log_context={"email": _EMAIL, "phone": _PHONE, "n": 1})

    @router.get("/by-model")
    def by_model() -> dict[str, str]:
        raise NotFoundError(log_context={"customer": _read()})

    @router.get("/logged")
    def logged() -> dict[str, str]:
        log.info("customer %s", _read(), extra={"customer": _read(), "email": _EMAIL})
        log.info(f"customer {_read()}")  # noqa: G004 - the f-string is the path under test
        return {}

    @router.get("/boom")
    def boom() -> dict[str, str]:
        raise RuntimeError(f"cannot bill {_read()}")

    @router.get("/invalid")
    def invalid() -> dict[str, str]:
        _Strict(email=_EMAIL)
        return {}

    return _compose(router)


@pytest.mark.parametrize(
    ("path", "status"),
    [
        (f"/api/v1/pii/customers/{uuid.uuid4()}?email={_EMAIL}", 200),
        ("/api/v1/pii/by-name", 404),
        ("/api/v1/pii/by-model", 404),
        ("/api/v1/pii/logged", 200),
        ("/api/v1/pii/boom", 500),
        ("/api/v1/pii/invalid", 500),
    ],
)
def test_no_request_path_writes_a_declared_value(path: str, status: int) -> None:
    client = TestClient(_app(), raise_server_exceptions=False)
    with captured() as everything:
        assert client.get(path, headers=_AUTH).status_code == status
    lines = _served(everything)
    assert lines, "the request wrote no line at all"
    for line in lines:
        assert_record(line)
    _no_personal_value_in(json.dumps(lines))
    access = [line for line in lines if line.get("event") == "http.access"]
    assert len(access) == 1  # held by construction: a template, a status, ids
    errors = [line for line in lines if line.get("event") in {"error.app", "error.unhandled"}]
    if status != 200:
        assert len(errors) == 1
    if path.endswith("by-name"):
        assert errors[0]["context"] == {"email": PERSONAL, "phone": PERSONAL, "n": 1}
    if path.endswith(("by-model", "boom", "logged")):
        assert PERSONAL in json.dumps(lines)


# --------------------------------------------------------------------------- #
# the database's refusal
# --------------------------------------------------------------------------- #
@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine, tables=[_Customer.__table__])  # type: ignore[attr-defined]
    try:
        with Session(engine) as active:
            yield active
    finally:
        engine.dispose()


def test_a_refused_duplicate_does_not_log_the_address(session: Session) -> None:
    _Customers().create(session, _CustomerCreate(email=_EMAIL, phone=_PHONE))
    with pytest.raises(ConflictError) as refused:
        _Customers().create(session, _CustomerCreate(email=_EMAIL, phone=_PHONE))
    detail = refused.value.log_context["integrity_error"]
    assert "UNIQUE" in detail and PERSONAL in detail
    _no_personal_value_in(detail)


def test_every_row_in_flight_loses_its_values(session: Session) -> None:
    first, second = _Customer(email=_EMAIL), _Customer(email=_OTHER_EMAIL, phone=_PHONE)
    session.add(first)
    session.add(second)
    exc = IntegrityError("INSERT", {"a": _EMAIL, "b": _OTHER_EMAIL, "c": _PHONE}, Exception("dup"))
    _no_personal_value_in(_integrity_detail(exc, session, first))
    session.expunge_all()


def test_withholding_takes_the_longest_value_first_and_skips_empty_ones() -> None:
    row = _Customer(email=f"{_PHONE}@example.test", phone=_PHONE, note="n")
    text = f"Key (email)=({_PHONE}@example.test) and ({_PHONE})"
    assert withhold_personal_values(text, row) == f"Key (email)=({PERSONAL}) and ({PERSONAL})"
    assert withhold_personal_values("nothing here", _Customer(email="", phone=None)) == "nothing here"


# --------------------------------------------------------------------------- #
# the audit trail
# --------------------------------------------------------------------------- #
def test_an_audit_payload_keeps_the_key_and_loses_the_value() -> None:
    redacted = AuditPolicy.default().redact(
        {
            "email": _EMAIL,
            "api_token": _TOKEN,
            "nested": {"phone": _PHONE, "status": "open"},
            "customer": _read(),
            "rows": [_read()],
            "pair": (_Contact(email=_EMAIL),),
            "count": 2,
        }
    )
    assert redacted is not None
    _no_personal_value_in(json.dumps(redacted, default=str))
    assert redacted["email"] == PERSONAL
    assert redacted["api_token"] == "***redacted***"
    assert redacted["nested"] == {"phone": PERSONAL, "status": "open"}
    assert redacted["customer"]["email"] == PERSONAL
    assert redacted["customer"]["note"] == "vip"
    assert redacted["customer"]["tags"] == [{"label": "lead", "owner_email": PERSONAL}]
    assert redacted["rows"][0]["email"] == PERSONAL
    assert redacted["pair"] == ({"email": PERSONAL, "city": ""},)
    assert redacted["count"] == 2


def test_the_audit_sinks_never_receive_a_declared_value(terp_audit: Any) -> None:
    received: list[Any] = []
    terp_audit(AuditPolicy.default(), sink=lambda _session, record, _policy: received.append(record))
    emit_audit(
        None,  # type: ignore[arg-type] - the capturing sink never touches it
        action=AuditAction.UPDATED,
        target_type="customer",
        target_id="1",
        payload={"email": _EMAIL, "customer": _read()},
    )
    (record,) = received
    _no_personal_value_in(json.dumps(dict(record.payload), default=str))
    # And the default sink, which writes the record to the log.
    terp_audit(AuditPolicy.default())
    audit_logger = logging.getLogger("terp.core.audit")
    level = audit_logger.level
    audit_logger.setLevel(logging.INFO)
    try:
        with captured() as lines:
            emit_audit(None, action=AuditAction.CREATED, target_type="customer",  # type: ignore[arg-type]
                       target_id="1", payload={"email": _EMAIL})
    finally:
        audit_logger.setLevel(level)
    assert lines and PERSONAL in json.dumps(lines)
    _no_personal_value_in(json.dumps(lines))


# --------------------------------------------------------------------------- #
# events and jobs
# --------------------------------------------------------------------------- #
def test_a_public_payload_cannot_declare_a_personal_field() -> None:
    with pytest.raises(ValueError, match="PUBLIC"):
        EventDefinition("pii.customer.seen", payload_schema=_CustomerRead,
                        visibility=EventVisibility.PUBLIC)
    with pytest.raises(ValueError, match="email"):
        JobDefinition("pii.customer.send", payload_schema=_CustomerRead,
                      handler=lambda _ctx, _payload: None, visibility=JobVisibility.PUBLIC)
    # The same schema is fine where it is not surfaced outward, and a public payload
    # without a personal field is fine too.
    EventDefinition("pii.customer.changed", payload_schema=_CustomerRead)
    EventDefinition("pii.city.public", payload_schema=_City, visibility=EventVisibility.PUBLIC)
    JobDefinition("pii.customer.sync", payload_schema=_CustomerRead,
                  handler=lambda _ctx, _payload: None, visibility=JobVisibility.RESTRICTED)


def test_the_copy_of_a_payload_that_leaves_the_process() -> None:
    class _PlainPayload(BaseModel):
        """A payload schema with no Terp base: its names are not collected, so pass it."""

        contact_phone: str = Personal(default="")
        city: str = ""

    payload = {"contact_phone": _PHONE, "city": "Delft", "email": _EMAIL, "list": [{"phone": _PHONE}]}
    redacted = redact_personal(payload, model=_PlainPayload)
    assert redacted == {"contact_phone": PERSONAL, "city": "Delft", "email": PERSONAL,
                        "list": [{"phone": PERSONAL}]}
    assert redact_personal(payload)["contact_phone"] == _PHONE  # nothing declared it
    assert redact_personal((_read(),))[0]["email"] == PERSONAL
    assert redact_personal(_Envelope(customer=_read(), label="x"))["customer"]["email"] == PERSONAL
    assert redact_personal(7) == 7
