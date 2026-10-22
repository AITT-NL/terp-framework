"""Every log line is a ``terp-log/1`` record, and says what the framework promises (ADR 0188).

The format is a contract with a reader the framework never sees: a deploy tool reading a
container's lines, a log store indexing them, an operator piping them through ``jq``. Those
readers hold the lines of an older release beside a newer one's, so the contract is the
schema shipped with terp-core (``log-record.schema.json``), every line is held to it here,
and the schema only grows by addition.

What each line promises is held beside it:

* **the record** -- a UTC millisecond timestamp and the schema id on every line; rendering
  and redaction never raise, and never print a plain traceback instead;
* **the access line** -- exactly one per request, naming the route template and never the
  requested path, the status, the duration, the request id, and the actor and tenant only
  when the request was authenticated;
* **the guard** -- the rule that decided, for every allow and every deny, on the access
  line rather than as a line of its own;
* **errors** -- each ``AppError`` once, with its redacted ``log_context``; an unexpected
  exception once, joined to its request by id;
* **the process** -- uvicorn's loggers, uncaught exceptions and warnings through the same
  handler, and a refused configuration that does not print the configuration.

``test_structured_logs_served.py`` proves the same against a real uvicorn process in
production mode, which is the place the plain-text lines used to come from.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import logging
import logging.config
import secrets
import sys
import threading
import uuid
import warnings
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from starlette.requests import HTTPConnection

import terp.core._request_log as request_log
import terp.core.config as config_module
import terp.core.logging as terp_logging
from terp.core import (
    EDITOR,
    LOG_SCHEMA,
    VIEWER,
    AppError,
    ControlPlane,
    ModuleSpec,
    NotFoundError,
    Permission,
    Policy,
    Principal,
    RateLimit,
    SecurityConfig,
    CorsPolicy,
    create_app,
    log_record_schema,
    register_log_tenant_reader,
    route_policy,
)
from terp.core.app import build_guard
from terp.core.config import Settings
import terp.core._log_capture as log_capture
from terp.core._log_capture import (
    _log_uncaught,
    _log_uncaught_in_thread,
    _log_unraisable,
    _show_warning,
    reset_logging_runtime,
)
from terp.core._log_capture import capture_process as _capture_process
from terp.core._log_capture import route_server_loggers as _route_server_loggers
from terp.core.logging import (
    TOP_LEVEL_FIELDS,
    RedactingFilter,
    StructuredFormatter,
    _protect_handler,
    _StructuredStreamHandler,
    configure_logging,
    log_fields,
)
from terp.core._request_log import (
    ACCESS_SCOPE_KEY,
    CLIENT_CLOSED,
    AccessLogMiddleware,
    note_guard_decision,
)

_SCHEMA = log_record_schema()
_VALIDATOR = Draft202012Validator(_SCHEMA)

_ACTOR = uuid.UUID("3f0c1d1e-8a54-4b1e-9d1a-2b7a5c9e0f11")
_TENANT = uuid.UUID("7d2b9c40-1f3e-4a5b-8c6d-0e9f1a2b3c4d")
# Fixture credentials: what the assertions below look for, so each must be distinctive.
# Generated per run (ADR 0163), never written down: a literal here would be a credential-shaped
# string in the history every secret scan reads.
_TOKEN = "tok-" + secrets.token_hex(6)
_PASSWORD = "pw-" + secrets.token_hex(5)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def assert_record(line: dict[str, Any]) -> None:
    """*line* validates against the schema and uses only keys the schema declares.

    The schema is tolerant upward on purpose -- a reader must accept a key a later 1.x
    adds -- so the second half is the emitter's own strictness: a key the framework
    writes that the schema does not name is a schema change nobody made.
    """
    errors = sorted(error.message for error in _VALIDATOR.iter_errors(line))
    assert errors == [], f"{line!r} breaks terp-log/1: {errors}"
    assert set(line) <= set(_SCHEMA["properties"]), sorted(set(line) - set(_SCHEMA["properties"]))
    for key in ("http", "guard", "error"):
        if key in line:
            declared = set(_SCHEMA["$defs"][key]["properties"])
            assert set(line[key]) <= declared, (key, sorted(set(line[key]) - declared))


@contextlib.contextmanager
def captured(level: int = logging.DEBUG) -> Iterator[list[dict[str, Any]]]:
    """Collect every record the root logger sees, as parsed ``terp-log/1`` lines."""
    stream = io.StringIO()
    handler = _protect_handler(logging.StreamHandler(stream))
    handler.setLevel(level)
    root = logging.getLogger()
    root.addHandler(handler)
    lines: list[dict[str, Any]] = []
    try:
        yield lines
    finally:
        root.removeHandler(handler)
        lines.extend(json.loads(text) for text in stream.getvalue().splitlines())


def _ours(lines: list[dict[str, Any]], logger: str) -> list[dict[str, Any]]:
    return [line for line in lines if line["logger"] == logger]


def _record(msg: object = "m", args: Any = None, **attrs: Any) -> logging.LogRecord:
    record = logging.LogRecord("probe", logging.INFO, "p", 1, msg, args, None)
    for key, value in attrs.items():
        setattr(record, key, value)
    return record


def _render(record: logging.LogRecord) -> dict[str, Any]:
    RedactingFilter().filter(record)
    return json.loads(StructuredFormatter().format(record))


def _principal(connection: HTTPConnection) -> Principal | None:
    if connection.headers.get("authorization") == f"Bearer {_TOKEN}":
        return Principal(id=_ACTOR, role=VIEWER)
    return None


class _Unavailable(AppError):
    status_code = 503
    code = "probe_unavailable"
    default_message = "The probe is unavailable."


def _app(principal: Any = _principal, security: SecurityConfig | None = None) -> FastAPI:
    router = APIRouter()

    @router.get("/items/{item_id}")
    def read_item(item_id: uuid.UUID) -> dict[str, str]:
        return {"id": str(item_id)}

    @router.post("/items")
    def write_item() -> dict[str, str]:
        return {}

    @router.get("/missing")
    def missing() -> dict[str, str]:
        raise NotFoundError(
            log_context={"token": _TOKEN, "cause": f"Authorization: Bearer {_TOKEN}", "n": 3}
        )

    @router.get("/bare")
    def bare() -> dict[str, str]:
        raise NotFoundError()

    @router.get("/unavailable")
    def unavailable() -> dict[str, str]:
        raise _Unavailable(log_context={"upstream": "ledger"})

    @router.get("/boom")
    def boom() -> dict[str, str]:
        raise RuntimeError(f"password={_PASSWORD}")

    @router.get("/open")
    @route_policy(Policy.public(reason="a probe route anyone may read"))
    def open_route() -> dict[str, str]:
        return {}

    nested = APIRouter()

    @nested.get("/things/{thing_id}")
    def thing(thing_id: uuid.UUID) -> dict[str, str]:
        return {"id": str(thing_id)}

    router.include_router(nested, prefix="/nested")
    plane = ControlPlane(security=security) if security is not None else None
    return create_app(
        [ModuleSpec(name="probe", router=router, policy=Policy.default())],
        principal_provider=principal,
        control_plane=plane,
    )


_AUTH = {"Authorization": f"Bearer {_TOKEN}"}


@pytest.fixture
def no_tenant_reader() -> Iterator[None]:
    """Restore whatever tenant reader was registered (tenancy registers one at import)."""
    previous = terp_logging._tenant_reader
    yield
    terp_logging._tenant_reader = previous


# --------------------------------------------------------------------------- #
# the schema
# --------------------------------------------------------------------------- #
def test_the_schema_is_a_valid_draft_2020_12_schema() -> None:
    Draft202012Validator.check_schema(_SCHEMA)
    assert _SCHEMA["$schema"] == "https://json-schema.org/draft/2020-12/schema"


def test_the_schema_declares_exactly_the_keys_the_formatter_writes() -> None:
    # One list in the formatter, one in the schema; a key in either alone is drift.
    assert set(_SCHEMA["properties"]) == set(TOP_LEVEL_FIELDS)
    assert _SCHEMA["properties"]["schema"]["const"] == LOG_SCHEMA == "terp-log/1"


def _valid_line(**overrides: Any) -> dict[str, Any]:
    line: dict[str, Any] = {
        "time": "2026-10-21T08:15:02.317Z",
        "schema": "terp-log/1",
        "level": "INFO",
        "logger": "probe",
        "request_id": "-",
        "message": "m",
    }
    line.update(overrides)
    return {key: value for key, value in line.items() if value is not None}


@pytest.mark.parametrize(
    ("overrides", "why"),
    [
        ({"time": None}, "a line without a timestamp"),
        ({"time": "2026-10-21T08:15:02Z"}, "a timestamp without milliseconds"),
        ({"time": "2026-10-21T08:15:02.317+02:00"}, "a timestamp that is not UTC"),
        ({"time": "2026-10-21T08:15:02.317Z\n"}, "a trailing newline Python's $ would admit"),
        ({"schema": "terp-log/2"}, "a line in another version"),
        ({"schema": None}, "a line that names no version"),
        ({"level": 20}, "a level that is not a string"),
        ({"request_id": "evil\ninjected"}, "a request id outside its shape"),
        ({"event": "http.access"}, "an access line without its http object"),
        ({"event": "http.access", "http": {"method": "GET"}}, "an access line without status"),
        ({"event": "error.app", "error": {"type": "X"}}, "an app error without its code"),
        ({"event": "guard.decision"}, "a guard record without its decision"),
        ({"tenant": str(_TENANT)}, "a tenant without an actor"),
        ({"actor": f"Bearer {_TOKEN}"}, "an actor that is not an id"),
        ({"guard": {"outcome": "maybe"}}, "a guard object outside its vocabulary"),
    ],
)
def test_the_schema_refuses_a_line_that_breaks_version_1(
    overrides: dict[str, Any], why: str
) -> None:
    assert list(_VALIDATOR.iter_errors(_valid_line(**overrides))), why


def test_the_schema_accepts_what_a_later_1_x_may_add() -> None:
    # Additive by construction: a key, an event, a nested field nobody knows yet.
    line = _valid_line(
        span="abc",
        event="queue.drained",
        http={"method": "GET", "status": 200, "duration_ms": 1.5, "bytes": 12},
    )
    assert list(_VALIDATOR.iter_errors(line)) == []


# --------------------------------------------------------------------------- #
# the record: timestamp, schema id, and a log call that never raises
# --------------------------------------------------------------------------- #
def test_every_line_carries_a_utc_millisecond_timestamp_and_the_schema() -> None:
    record = _record("hello")
    record.created = 1_792_000_000.25
    record.msecs = 250.0
    line = json.loads(StructuredFormatter().format(record))
    assert line["time"] == "2026-10-14T17:46:40.250Z"
    assert line["schema"] == "terp-log/1"
    assert_record(line)


def test_a_record_that_cannot_be_rendered_becomes_a_log_failure_line() -> None:
    # "%d" with a string: getMessage raises TypeError inside the formatter.
    line = json.loads(StructuredFormatter().format(_record("%d items", ("many",))))
    assert line["event"] == "log.failure"
    assert line["error"] == {"type": "TypeError"}
    assert line["message"] == "a log record could not be rendered"
    assert_record(line)


def test_a_record_that_cannot_be_redacted_is_withheld() -> None:
    class Unprintable:
        def __str__(self) -> str:
            raise RuntimeError(f"password={_PASSWORD}")

    record = _record(Unprintable(), note=f"Bearer {_TOKEN}")
    assert RedactingFilter().filter(record) is True
    rendered = StructuredFormatter().format(record)
    line = json.loads(rendered)
    assert line["event"] == "log.failure"
    assert line["message"] == "a log record was withheld: redacting it failed"
    assert "extra" not in line
    assert _TOKEN not in rendered and _PASSWORD not in rendered
    assert_record(line)


def test_a_log_call_with_broken_arguments_never_raises_or_prints_plain_text(
    capsys: pytest.CaptureFixture[str],
) -> None:
    stream = io.StringIO()
    logger = logging.getLogger("terp.test.structured.broken")
    logger.propagate = False
    handler = _protect_handler(_StructuredStreamHandler(stream))
    logger.addHandler(handler)
    try:
        logger.error("%d of %d", "one")  # wrong count and wrong type
    finally:
        logger.removeHandler(handler)
    line = json.loads(stream.getvalue())
    assert line["event"] == "log.failure"
    assert "--- Logging error ---" not in capsys.readouterr().err


class _BrokenStream:
    """A stream whose first *failures* writes raise, as a closed pipe does."""

    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.written: list[str] = []

    def write(self, text: str) -> None:
        if self.failures:
            self.failures -= 1
            raise OSError("broken pipe")
        self.written.append(text)

    def flush(self) -> None:
        return None


def test_a_failed_write_is_retried_once_in_the_record_shape(
    capsys: pytest.CaptureFixture[str],
) -> None:
    stream = _BrokenStream(failures=1)
    handler = _protect_handler(_StructuredStreamHandler(stream))  # type: ignore[arg-type]
    handler.handle(_record("hello"))
    line = json.loads(stream.written[0])
    assert line["event"] == "log.failure" and line["error"] == {"type": "OSError"}
    assert "Traceback" not in capsys.readouterr().err


def test_a_stream_that_refuses_every_write_is_dropped_silently(
    capsys: pytest.CaptureFixture[str],
) -> None:
    handler = _protect_handler(_StructuredStreamHandler(_BrokenStream(failures=99)))  # type: ignore[arg-type]
    handler.handle(_record("hello"))  # no raise
    assert capsys.readouterr().err == ""


def test_uvicorns_coloured_copy_of_its_message_is_not_written() -> None:
    line = _render(_record("Started server process [%d]", (7,), color_message="\x1b[36m%d\x1b[0m"))
    assert line["message"] == "Started server process [7]"
    assert "extra" not in line


def test_framework_fields_are_lifted_to_the_top_and_app_fields_stay_in_extra() -> None:
    record = _record("m", **log_fields(event="http.access", http={"method": "GET",
                     "status": 200, "duration_ms": 0.5}, actor=None), audit_action="x")
    line = _render(record)
    assert line["event"] == "http.access" and line["http"]["status"] == 200
    assert "actor" not in line  # None is absent, never null
    assert line["extra"] == {"audit_action": "x"}
    assert_record(line)


def test_stack_info_is_redacted() -> None:
    line = _render(_record("m", stack_info=f'  File "x.py"\n    call(token="{_TOKEN}")'))
    assert _TOKEN not in line["stack_info"]
    assert_record(line)


def test_the_formatter_alone_still_redacts_what_it_renders() -> None:
    # Without the filter (a handler someone else configured), the formatter still scrubs
    # the rendered message and the traceback it renders itself.
    try:
        raise ValueError(f"Authorization: Bearer {_TOKEN}")
    except ValueError:
        record = logging.LogRecord("p", logging.ERROR, "p", 1, "x %s", (f"Bearer {_TOKEN}",),
                                   sys.exc_info())
    rendered = StructuredFormatter().format(record)
    assert _TOKEN not in rendered
    stack = _record("m")
    stack.stack_info = f"password={_PASSWORD}"
    assert _PASSWORD not in StructuredFormatter().format(stack)


# --------------------------------------------------------------------------- #
# redaction: secrets, by key and by shape -- and only secrets
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("text", "kept"),
    [
        # The shape that used to leak: the scheme word was redacted, the credential kept.
        (f"headers: Authorization: Bearer {_TOKEN}", "Authorization: Bearer [REDACTED]"),
        (f"Authorization=Basic {_TOKEN}", "Authorization=Basic [REDACTED]"),
        (f'{{"authorization": "{_TOKEN}"}}', '"authorization": "[REDACTED]"'),
        (f"retry with Bearer {_TOKEN}", "Bearer [REDACTED]"),
        (f"Cookie: session={_TOKEN}; theme=dark", "Cookie: [REDACTED]"),
        (f"postgresql://app:{_PASSWORD}@db:5432/app", "postgresql://app:[REDACTED]@db:5432/app"),
        (f"connect(password={_PASSWORD})", "password=[REDACTED]"),
        (f"client_secret: '{_PASSWORD}'", "client_secret: '[REDACTED]"),
        (f"?api_key={_TOKEN}&page=2", "api_key=[REDACTED]&page=2"),
    ],
)
def test_free_text_secrets_are_redacted(text: str, kept: str) -> None:
    line = _render(_record(text))
    assert _TOKEN not in line["message"] and _PASSWORD not in line["message"]
    assert kept in line["message"]


def test_a_placeholder_in_a_template_survives_and_its_value_does_not() -> None:
    # Redacting the template's "%s" would break the format string; the value appears
    # only once the arguments are in, and is scrubbed there.
    line = _render(_record("password=%s for %s", (_PASSWORD, "ada")))
    assert line["message"] == "password=[REDACTED] for ada"
    assert "event" not in line


def test_an_exception_logged_as_an_argument_is_redacted() -> None:
    line = _render(_record("call failed: %s", (ValueError(f"token={_TOKEN}"),)))
    assert _TOKEN not in line["message"]


def test_an_object_logged_as_the_message_is_redacted() -> None:
    line = _render(_record(ValueError(f"Authorization: Bearer {_TOKEN}")))
    assert line["message"] == "Authorization: Bearer [REDACTED]"


def test_tracebacks_are_redacted() -> None:
    stream = io.StringIO()
    logger = logging.getLogger("terp.test.structured.traceback")
    logger.propagate = False
    handler = _protect_handler(logging.StreamHandler(stream))
    logger.addHandler(handler)
    try:
        try:
            raise ConnectionError(f"postgresql://app:{_PASSWORD}@db/app refused Bearer {_TOKEN}")
        except ConnectionError:
            logger.exception("database unreachable")
    finally:
        logger.removeHandler(handler)
    line = json.loads(stream.getvalue())
    assert "ConnectionError" in line["exc_info"]
    assert _PASSWORD not in line["exc_info"] and _TOKEN not in line["exc_info"]
    assert_record(line)


def test_redaction_recognises_secrets_and_only_secrets() -> None:
    # The documented boundary: nothing here knows which field holds personal data, so an
    # address passes through. A later field-level marker is what will change this line.
    line = _render(_record("invited %s", ("ada@example.com",)))
    assert line["message"] == "invited ada@example.com"


# --------------------------------------------------------------------------- #
# the access line
# --------------------------------------------------------------------------- #
def test_one_access_line_per_request_with_every_field() -> None:
    client = TestClient(_app())
    item = uuid.uuid4()
    with captured() as lines:
        response = client.get(f"/api/v1/probe/items/{item}", headers=_AUTH)
    assert response.status_code == 200
    access = _ours(lines, "terp.access")
    assert len(access) == 1
    line = access[0]
    assert line["event"] == "http.access"
    assert line["http"]["method"] == "GET"
    assert line["http"]["route"] == "/api/v1/probe/items/{item_id}"
    assert line["http"]["status"] == 200
    assert line["http"]["duration_ms"] >= 0
    assert line["request_id"] == response.headers["X-Request-ID"]
    assert line["actor"] == str(_ACTOR)
    assert line["message"] == "GET /api/v1/probe/items/{item_id} 200"
    assert_record(line)
    # Never the requested path, and never the credential that authenticated it.
    rendered = json.dumps(line)
    assert str(item) not in rendered and _TOKEN not in rendered


def test_a_nested_router_route_is_named_by_its_full_template() -> None:
    with captured() as lines:
        TestClient(_app()).get(f"/api/v1/probe/nested/things/{uuid.uuid4()}", headers=_AUTH)
    (line,) = _ours(lines, "terp.access")
    assert line["http"]["route"] == "/api/v1/probe/nested/things/{thing_id}"


def test_the_route_template_falls_back_to_the_matched_route() -> None:
    # An app built on a FastAPI that copies routes onto the app keeps the prefix in the
    # route's own path and has no per-request route context.
    route = SimpleNamespace(path="/api/v1/notes/{note_id}")
    assert request_log._route_template({"route": route}) == "/api/v1/notes/{note_id}"
    assert request_log._route_template({"fastapi": {}, "route": None}) is None
    assert request_log._route_template({"fastapi": "unexpected"}) is None


def test_an_unmatched_request_names_no_route() -> None:
    with captured() as lines:
        TestClient(_app()).get(f"/api/v1/probe/elsewhere/{uuid.uuid4()}")
    (line,) = _ours(lines, "terp.access")
    assert "route" not in line["http"] and line["http"]["status"] == 404
    assert line["message"] == "GET - 404"
    assert_record(line)


def test_an_unauthenticated_request_names_no_actor_and_no_tenant(no_tenant_reader: None) -> None:
    register_log_tenant_reader(lambda: _TENANT)
    with captured() as lines:
        TestClient(_app()).get(f"/api/v1/probe/items/{uuid.uuid4()}")
    (line,) = _ours(lines, "terp.access")
    assert line["http"]["status"] == 401
    assert "actor" not in line and "tenant" not in line
    assert line["guard"]["rule"] == "authenticated"


def test_the_tenant_is_written_beside_the_authenticated_actor(no_tenant_reader: None) -> None:
    register_log_tenant_reader(lambda: _TENANT)
    with captured() as lines:
        TestClient(_app()).get(f"/api/v1/probe/items/{uuid.uuid4()}", headers=_AUTH)
    (line,) = _ours(lines, "terp.access")
    assert (line["actor"], line["tenant"]) == (str(_ACTOR), str(_TENANT))
    assert_record(line)


def test_the_tenancy_capability_registers_its_reader() -> None:
    from terp.capabilities.tenancy import current_tenant_id, tenant_context

    assert terp_logging._tenant_reader is current_tenant_id
    with tenant_context(_TENANT):
        assert terp_logging.active_log_tenant() == _TENANT


def test_an_actor_that_is_not_an_id_is_never_written(no_tenant_reader: None) -> None:
    # A principal provider that put the credential itself in the id: the field holds a
    # UUID or nothing, so the token cannot reach the line through it.
    register_log_tenant_reader(lambda: f"Bearer {_TOKEN}")  # type: ignore[arg-type,return-value]
    leaky = lambda connection: Principal(id=f"Bearer {_TOKEN}", role=VIEWER)  # type: ignore[arg-type]  # noqa: E731
    with captured() as lines:
        TestClient(_app(principal=leaky)).get(f"/api/v1/probe/items/{uuid.uuid4()}")
    (line,) = _ours(lines, "terp.access")
    assert "actor" not in line and "tenant" not in line
    assert _TOKEN not in json.dumps(lines)


def test_an_exception_that_escapes_every_handler_is_a_500_access_line() -> None:
    with captured() as lines:
        response = TestClient(_app(), raise_server_exceptions=False).get(
            "/api/v1/probe/boom", headers=_AUTH
        )
    assert response.status_code == 500
    (access,) = _ours(lines, "terp.access")
    (error,) = [line for line in lines if line.get("event") == "error.unhandled"]
    assert access["http"]["status"] == 500
    # Joined by request id: the unhandled handler runs outside the request-id middleware,
    # which has reset the correlation id by then (and the 500 carries it in its body).
    assert error["request_id"] == access["request_id"] == response.json()["request_id"]
    assert error["error"] == {"type": "RuntimeError", "code": "internal_error", "status": 500}
    assert _PASSWORD not in error["exc_info"]
    assert_record(access)
    assert_record(error)


def test_a_refusal_before_routing_still_gets_its_access_line() -> None:
    security = SecurityConfig(
        cors=CorsPolicy.disabled(reason="api only"),
        rate_limit=RateLimit(requests=1, window_seconds=60),
    )
    client = TestClient(_app(security=security))
    with captured() as lines:
        client.get("/api/v1/probe/open")
        refused = client.get("/api/v1/probe/open")
    assert refused.status_code == 429
    statuses = [line["http"]["status"] for line in _ours(lines, "terp.access")]
    assert statuses == [200, 429]


def _run(app: Any, scope: dict[str, Any]) -> list[dict[str, Any]]:
    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(_message: dict[str, Any]) -> None:
        return None

    async def call() -> None:
        await AccessLogMiddleware(app)(scope, receive, send)

    with captured() as lines:
        with contextlib.suppress(Exception, asyncio.CancelledError):
            asyncio.run(call())
    return _ours(lines, "terp.access")


def test_a_request_the_client_abandons_is_written_as_499() -> None:
    async def abandoned(scope: Any, receive: Any, send: Any) -> None:
        raise asyncio.CancelledError

    (line,) = _run(abandoned, {"type": "http", "method": "GET"})
    assert line["http"]["status"] == CLIENT_CLOSED == 499
    assert_record(line)


def test_an_exception_before_any_response_is_written_as_500() -> None:
    async def failing(scope: Any, receive: Any, send: Any) -> None:
        raise RuntimeError("nothing started")

    (line,) = _run(failing, {"type": "http", "method": "GET"})
    assert line["http"]["status"] == 500


def test_a_websocket_passes_through_without_an_access_line() -> None:
    seen: list[str] = []

    async def socket_app(scope: Any, receive: Any, send: Any) -> None:
        seen.append(scope["type"])

    assert _run(socket_app, {"type": "websocket"}) == []
    assert seen == ["websocket"]


def test_the_access_line_never_breaks_a_response(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("the log is down")

    monkeypatch.setattr(request_log._access_logger, "info", explode)
    with captured() as lines:
        response = TestClient(_app()).get("/api/v1/probe/open")
    assert response.status_code == 200
    (failure,) = [line for line in lines if line.get("event") == "log.failure"]
    assert failure["message"] == "an access line could not be recorded"
    assert_record(failure)


# --------------------------------------------------------------------------- #
# the guard: the deciding rule, for every allow and deny
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("method", "path", "headers", "guard"),
    [
        ("GET", "/items/{id}", _AUTH, {"outcome": "allow", "reason": "allowed",
                                        "rule": "role:viewer", "policy": "module",
                                        "tier": "read", "module": "probe"}),
        ("POST", "/items", _AUTH, {"outcome": "deny", "reason": "rank", "rule": "role:editor",
                                   "policy": "module", "tier": "write", "module": "probe"}),
        ("GET", "/items/{id}", {}, {"outcome": "deny", "reason": "unauthenticated",
                                    "rule": "authenticated", "policy": "module",
                                    "tier": "read", "module": "probe"}),
        ("GET", "/open", {}, {"outcome": "allow", "reason": "public", "rule": "public",
                              "policy": "route", "tier": "read", "module": "probe"}),
    ],
)
def test_the_access_line_carries_the_guards_deciding_rule(
    method: str, path: str, headers: dict[str, str], guard: dict[str, str]
) -> None:
    client = TestClient(_app())
    with captured() as lines:
        client.request(method, "/api/v1/probe" + path.replace("{id}", str(uuid.uuid4())),
                       headers=headers)
    (line,) = _ours(lines, "terp.access")
    assert line["guard"] == guard
    # The decision rides the access line: no record of its own, at any level.
    assert _ours(lines, "terp.guard") == []
    assert_record(line)


def test_a_permission_decision_names_the_permission() -> None:
    publish = Permission("probe.publish", min_role=EDITOR)
    guard = build_guard(
        Policy(read=VIEWER, write=publish),
        permission_enforcer=lambda _session, _subject, _name: False,
        module_name="probe",
    )
    notes: dict[str, Any] = {}
    connection = SimpleNamespace(scope={"type": "http", "method": "POST", ACCESS_SCOPE_KEY: notes})
    with pytest.raises(AppError):
        guard(connection, principal=Principal(id=_ACTOR, role=EDITOR), session=None)
    assert notes["guard"] == {"outcome": "deny", "reason": "grant",
                              "rule": "permission:probe.publish", "policy": "module",
                              "tier": "write", "module": "probe"}
    assert notes["actor"] == str(_ACTOR)


def test_a_decision_without_an_access_line_is_its_own_record(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # A WebSocket, or a direct call: no access line to ride, so the guard writes one --
    # a deny at INFO, an allow at DEBUG, so allows never fill a production log.
    caplog.set_level(logging.DEBUG, logger="terp.guard")
    guard = build_guard(Policy.default())
    with captured() as lines:
        guard(SimpleNamespace(method="GET"), principal=Principal(id=_ACTOR, role=VIEWER),
              session=None)
        with pytest.raises(AppError):
            guard(SimpleNamespace(method="POST"), principal=None, session=None)
    allow, deny = _ours(lines, "terp.guard")
    assert (allow["level"], allow["guard"]["outcome"], allow["actor"]) == (
        "DEBUG", "allow", str(_ACTOR))
    assert (deny["level"], deny["guard"]["rule"]) == ("INFO", "authenticated")
    assert "module" not in deny["guard"] and "actor" not in deny
    for line in (allow, deny):
        assert line["event"] == "guard.decision"
        assert_record(line)


def test_recording_a_decision_never_changes_it(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*_args: Any, **_kwargs: Any) -> dict[str, str]:
        raise RuntimeError("cannot describe")

    monkeypatch.setattr(request_log, "guard_fields", explode)
    guard = build_guard(Policy.default())
    with captured() as lines:
        guard(SimpleNamespace(method="GET"), principal=Principal(id=_ACTOR, role=VIEWER),
              session=None)  # still allowed
        with pytest.raises(AppError):
            guard(SimpleNamespace(method="POST"), principal=None, session=None)  # still denied
    failures = [line for line in lines if line.get("event") == "log.failure"]
    assert [line["message"] for line in failures] == ["a guard decision could not be recorded"] * 2


def test_note_guard_decision_tolerates_a_scope_that_is_not_a_mapping(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="terp.guard")
    decision = SimpleNamespace(allowed=True, reason="allowed", requirement=None)
    with captured() as lines:
        note_guard_decision(None, decision, module=None, policy="module", tier="read",
                            actor_id=None)
    (line,) = _ours(lines, "terp.guard")
    assert line["guard"]["rule"] == "allowed"


# --------------------------------------------------------------------------- #
# errors: each logged once, with its redacted context
# --------------------------------------------------------------------------- #
def test_each_app_error_is_logged_once_with_its_redacted_context() -> None:
    with captured() as lines:
        response = TestClient(_app()).get("/api/v1/probe/missing", headers=_AUTH)
    assert response.status_code == 404
    assert _TOKEN not in response.text  # log_context never reaches the client
    errors = [line for line in lines if line.get("event", "").startswith("error.")]
    assert len(errors) == 1
    (error,) = errors
    assert (error["logger"], error["level"]) == ("terp.errors", "INFO")
    assert error["error"] == {"type": "NotFoundError", "code": "not_found", "status": 404}
    assert error["context"] == {
        "token": "[REDACTED]", "cause": "Authorization: Bearer [REDACTED]", "n": 3,
    }
    assert "exc_info" not in error
    assert error["request_id"] == response.headers["X-Request-ID"]
    assert _TOKEN not in json.dumps(lines)
    assert_record(error)


def test_an_app_error_without_context_writes_no_context() -> None:
    with captured() as lines:
        TestClient(_app()).get("/api/v1/probe/bare", headers=_AUTH)
    (error,) = _ours(lines, "terp.errors")
    assert "context" not in error


def test_a_server_side_app_error_is_an_error_with_its_traceback() -> None:
    with captured() as lines:
        response = TestClient(_app()).get("/api/v1/probe/unavailable", headers=_AUTH)
    assert response.status_code == 503
    (error,) = _ours(lines, "terp.errors")
    assert error["level"] == "ERROR"
    assert error["context"] == {"upstream": "ledger"}
    assert "_Unavailable" in error["exc_info"]
    assert_record(error)


def test_a_denial_is_one_access_line_and_one_error_record() -> None:
    with captured() as lines:
        TestClient(_app()).post("/api/v1/probe/items", headers=_AUTH)
    ours = [line for line in lines if line["logger"].startswith("terp.")]
    assert sorted(line["event"] for line in ours) == ["error.app", "http.access"]
    (error,) = _ours(lines, "terp.errors")
    assert error["error"]["code"] == "permission_denied"


# --------------------------------------------------------------------------- #
# the process: uvicorn, uncaught exceptions, warnings, a refused configuration
# --------------------------------------------------------------------------- #
@pytest.fixture
def server_loggers() -> Iterator[None]:
    names = ("uvicorn", "uvicorn.error", "uvicorn.access", "uvicorn.asgi")
    saved = {
        name: (list(logging.getLogger(name).handlers), logging.getLogger(name).propagate,
               logging.getLogger(name).level)
        for name in names
    }
    filters = list(logging.getLogger("uvicorn.error").filters)
    yield
    for name, (handlers, propagate, level) in saved.items():
        logger = logging.getLogger(name)
        logger.handlers[:] = handlers
        logger.propagate = propagate
        logger.setLevel(level)
    logging.getLogger("uvicorn.error").filters[:] = filters


def test_uvicorns_loggers_are_re_pointed_at_the_root_handler(server_loggers: None) -> None:
    # What uvicorn's command line does before it imports the app...
    from uvicorn.config import LOGGING_CONFIG

    logging.config.dictConfig(LOGGING_CONFIG)
    assert logging.getLogger("uvicorn").handlers and not logging.getLogger("uvicorn").propagate
    # ...and what the composition root does after.
    _route_server_loggers()
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        assert logging.getLogger(name).handlers == []
        assert logging.getLogger(name).propagate is True
    # uvicorn's own access line (the raw path, query string and all) is retired.
    assert not logging.getLogger("uvicorn.access").isEnabledFor(logging.INFO)
    with captured() as lines:
        logging.getLogger("uvicorn.error").info("Started server process [%d]", 7,
                                                extra={"color_message": "\x1b[36m"})
        logging.getLogger("uvicorn.access").info('127.0.0.1 - "GET /x?token=1" 200')
    (line,) = _ours(lines, "uvicorn.error")
    assert line["message"] == "Started server process [7]"
    assert _ours(lines, "uvicorn.access") == []
    assert_record(line)


def test_the_servers_copy_of_an_exception_already_written_is_dropped(
    server_loggers: None,
) -> None:
    _route_server_loggers()
    _route_server_loggers()  # idempotent: one filter, however often the root is configured
    server = logging.getLogger("uvicorn.error")
    assert sum(isinstance(f, log_capture._AlreadyLoggedFilter) for f in server.filters) == 1
    written, fresh = RuntimeError("answered with a 500"), RuntimeError("never answered")
    log_capture.mark_logged(written)
    with captured() as lines:
        server.error("Exception in ASGI application", exc_info=written)
        server.error("Exception in ASGI application", exc_info=fresh)
        server.error("no exception at all")
    assert [("never answered" in line.get("exc_info", "")) for line in lines] == [True, False]


def test_marking_an_exception_that_takes_no_attributes_is_harmless() -> None:
    class Sealed(Exception):
        def __setattr__(self, name: str, value: object) -> None:
            raise AttributeError(name)

    sealed = Sealed()
    log_capture.mark_logged(sealed)  # no raise
    assert log_capture._AlreadyLoggedFilter().filter(_record("m", exc_info=None)) is True


def test_a_stricter_uvicorn_access_level_is_kept(server_loggers: None) -> None:
    logging.getLogger("uvicorn.access").setLevel(logging.ERROR)
    _route_server_loggers()
    assert logging.getLogger("uvicorn.access").level == logging.ERROR


@pytest.fixture
def default_hooks(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Run with the interpreter's own hooks, and put everything back afterwards."""
    monkeypatch.setattr(sys, "excepthook", sys.__excepthook__)
    monkeypatch.setattr(threading, "excepthook", threading.__excepthook__)
    monkeypatch.setattr(sys, "unraisablehook", sys.__unraisablehook__)
    monkeypatch.setattr(warnings, "showwarning", log_capture._INTERPRETER_SHOWWARNING)
    monkeypatch.setattr(log_capture, "_replaced_showwarning", None)
    yield


def test_process_capture_replaces_the_interpreters_default_printers(default_hooks: None) -> None:
    _capture_process()
    assert sys.excepthook is _log_uncaught
    assert threading.excepthook is _log_uncaught_in_thread
    assert sys.unraisablehook is _log_unraisable
    assert warnings.showwarning is _show_warning
    with captured() as lines:
        warnings.warn("a deprecated knob", UserWarning, stacklevel=1)
    (line,) = _ours(lines, "py.warnings")
    assert "a deprecated knob" in line["message"]
    assert_record(line)


def test_resetting_the_logging_runtime_puts_back_only_what_capture_installed(
    default_hooks: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _capture_process()
    _capture_process()  # idempotent: what it replaced is the interpreter's, not its own
    reset_logging_runtime()
    assert sys.excepthook is sys.__excepthook__
    assert threading.excepthook is threading.__excepthook__
    assert sys.unraisablehook is sys.__unraisablehook__
    assert warnings.showwarning is log_capture._INTERPRETER_SHOWWARNING
    theirs = lambda *_args: None  # noqa: E731
    monkeypatch.setattr(sys, "excepthook", theirs)
    monkeypatch.setattr(warnings, "showwarning", theirs)
    reset_logging_runtime()  # nothing of capture's is installed: theirs stays
    assert sys.excepthook is theirs and warnings.showwarning is theirs


def test_the_logging_runtime_is_a_seam_the_test_plugin_restores(default_hooks: None) -> None:
    from terp.core.runtime import capture_runtimes, restore_runtimes

    before = capture_runtimes()
    _capture_process()
    assert capture_runtimes()["logging"] != before["logging"]
    restore_runtimes(before)
    assert capture_runtimes()["logging"] == before["logging"]
    assert sys.excepthook is sys.__excepthook__


def test_a_warning_sent_to_an_explicit_file_still_goes_there(default_hooks: None) -> None:
    sent: list[str] = []
    log_capture._replaced_showwarning = lambda message, *_rest: sent.append(str(message))
    stream = io.StringIO()
    with captured() as lines:
        _show_warning("to the file", UserWarning, "x.py", 1, file=stream)
    assert sent == ["to the file"]
    assert _ours(lines, "py.warnings") == []


def test_process_capture_leaves_a_hook_someone_else_installed(
    default_hooks: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    theirs = lambda *_args: None  # noqa: E731
    monkeypatch.setattr(sys, "excepthook", theirs)
    monkeypatch.setattr(threading, "excepthook", theirs)
    monkeypatch.setattr(sys, "unraisablehook", theirs)
    _capture_process()
    assert sys.excepthook is threading.excepthook is sys.unraisablehook is theirs


def test_an_uncaught_exception_is_one_redacted_critical_record() -> None:
    error = RuntimeError(f"cannot reach postgresql://app:{_PASSWORD}@db/app")
    with captured() as lines:
        _log_uncaught(RuntimeError, error, error.__traceback__)
    (line,) = _ours(lines, "terp.uncaught")
    assert (line["level"], line["event"]) == ("CRITICAL", "error.uncaught")
    assert line["error"] == {"type": "RuntimeError"}
    assert line["message"].startswith("uncaught RuntimeError: cannot reach")
    assert _PASSWORD not in json.dumps(line)
    assert_record(line)


def test_an_exception_that_ends_a_thread_is_one_record() -> None:
    thread = threading.Thread(name="worker")
    error = ValueError(f"token={_TOKEN}")
    args = SimpleNamespace(exc_type=ValueError, exc_value=error, exc_traceback=None,
                           thread=thread)
    with captured() as lines:
        _log_uncaught_in_thread(args)  # type: ignore[arg-type]
        _log_uncaught_in_thread(SimpleNamespace(exc_type=SystemExit, exc_value=SystemExit(),  # type: ignore[arg-type]
                                                exc_traceback=None, thread=None))
        _log_uncaught_in_thread(SimpleNamespace(exc_type=KeyError, exc_value=KeyError("k"),  # type: ignore[arg-type]
                                                exc_traceback=None, thread=None))
    worker, unnamed = _ours(lines, "terp.uncaught")  # SystemExit is not an error
    assert worker["message"] == "uncaught ValueError in thread worker: token=[REDACTED]"
    assert unnamed["message"].startswith("uncaught KeyError in thread -:")
    assert_record(worker)


def test_an_unraisable_exception_is_one_record() -> None:
    with captured() as lines:
        _log_unraisable(SimpleNamespace(err_msg=None, exc_type=OSError,
                                        exc_value=OSError("closed"), exc_traceback=None))
        _log_unraisable(SimpleNamespace(err_msg="Exception ignored in finaliser",
                                        exc_type=OSError, exc_value=OSError("x"),
                                        exc_traceback=None))
    first, second = _ours(lines, "terp.uncaught")
    assert first["message"] == "Exception ignored"
    assert second["message"] == "Exception ignored in finaliser"
    assert first["level"] == "WARNING"
    assert_record(first)


@pytest.mark.parametrize(("environment", "captures"), [("local", False), ("staging", True)])
def test_create_app_configures_logging_first_and_captures_outside_local(
    monkeypatch: pytest.MonkeyPatch, environment: str, captures: bool
) -> None:
    import terp.core.app as app_module

    calls: list[bool] = []
    monkeypatch.setattr(config_module.settings, "ENVIRONMENT", environment)
    monkeypatch.setattr(app_module, "configure_logging",
                        lambda *, capture_process: calls.append(capture_process))
    with pytest.raises(Exception, match="capability_names requires"):
        # The very first boot check: logging is configured before it can refuse.
        create_app([], capability_names=("x",))
    assert calls == [captures]


def test_a_refused_configuration_does_not_print_the_configuration() -> None:
    with pytest.raises(ValidationError) as refused:
        Settings(
            ENVIRONMENT="production",
            SECRET_KEY="short",  # noqa: S106 - refused on purpose
            DATABASE_URL=f"postgresql+psycopg://app:{_PASSWORD}@db/app",
        )
    text = str(refused.value)
    assert "Insecure production configuration" in text
    assert _PASSWORD not in text and "short" not in text


def test_a_refused_configuration_is_written_as_a_record(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[bool] = []

    def refuse() -> Settings:
        return Settings(ENVIRONMENT="production")

    monkeypatch.setattr(config_module, "Settings", refuse)
    monkeypatch.setattr(config_module, "configure_logging",
                        lambda *, capture_process: calls.append(capture_process))
    with pytest.raises(ValidationError):
        config_module._load_settings()
    assert calls == [True]


def test_configure_logging_on_a_named_logger_touches_nothing_process_wide(
    default_hooks: None, server_loggers: None
) -> None:
    from uvicorn.config import LOGGING_CONFIG

    logging.config.dictConfig(LOGGING_CONFIG)
    logger = logging.getLogger("terp.test.structured.named")
    logger.handlers.clear()
    configure_logging(logger=logger, capture_process=True)
    assert sys.excepthook is sys.__excepthook__
    assert logging.getLogger("uvicorn").handlers
