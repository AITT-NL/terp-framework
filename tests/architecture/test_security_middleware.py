"""Phase C gate (runtime): the security middleware stack + structured logging.

Pairs with the build-time layer in ``test_arch_harness.py`` (the
``no_adhoc_middleware`` / ``no_adhoc_logging_config`` rules). These tests prove
each control is a *fail-closed runtime control*: security headers/CORS/limits/
request-id are installed by ``create_app``, the production guardrails refuse an
unsafe security config, and the logging layer redacts secrets and carries a
request-id.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import sys

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from terp.capabilities.audit import persist_audit
from terp.core import (
    AuditPolicy,
    BootError,
    ControlPlane,
    CorsPolicy,
    InMemoryThrottleStore,
    ModuleSpec,
    NotFoundError,
    Policy,
    RateLimit,
    SecurityConfig,
    SecurityHeaders,
    create_app,
    get_request_id,
    request_id_ctx,
    settings,
)
from terp.core.app import register_error_handlers
from terp.core.logging import (
    RedactingFilter,
    RequestContextFilter,
    StructuredFormatter,
    _REDACTED,
    configure_logging,
)
from terp.core._internal.middleware import (
    ClientIpMiddleware,
    RateLimitMiddleware,
    RequestIdMiddleware,
    RequestSizeLimitMiddleware,
    SecurityHeadersMiddleware,
    _declared_length,
    _forwarded_client_ip,
    _rate_limit_key,
)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
async def _ok(_request: Request) -> PlainTextResponse:
    return PlainTextResponse("ok")


def _starlette_app() -> Starlette:
    return Starlette(routes=[Route("/", _ok, methods=["GET", "POST"])])


def _probe_app(security: SecurityConfig) -> FastAPI:
    router = APIRouter()

    @router.get("/ping")
    def ping() -> dict:
        return {"ok": True}

    return create_app(
        [ModuleSpec(name="probe", router=router, policy=Policy.public(reason="probe route"))],
        control_plane=ControlPlane(security=security),
    )


# --------------------------------------------------------------------------- #
# SecurityHeaders / CorsPolicy / RateLimit / SecurityConfig (declarations)
# --------------------------------------------------------------------------- #
def test_security_headers_render_with_and_without_hsts() -> None:
    with_hsts = SecurityHeaders().as_headers(include_hsts=True)
    assert with_hsts["Strict-Transport-Security"]
    assert with_hsts["X-Frame-Options"] == "DENY"
    assert with_hsts["X-Content-Type-Options"] == "nosniff"
    assert "Strict-Transport-Security" not in SecurityHeaders().as_headers(include_hsts=False)
    # An explicitly-disabled HSTS never emits, even when included.
    assert "Strict-Transport-Security" not in SecurityHeaders(hsts=None).as_headers(
        include_hsts=True
    )


def test_cors_deny_all_is_unconfigured_and_closed() -> None:
    cors = CorsPolicy.deny_all()
    assert cors.configured is False
    assert cors.enabled is False
    assert cors.is_wildcard is False


def test_cors_disabled_is_an_explicit_optout() -> None:
    cors = CorsPolicy.disabled(reason="server-to-server only")
    assert cors.configured is True
    assert cors.enabled is False
    assert cors.disabled_reason == "server-to-server only"
    for bad in ("", "   "):
        with pytest.raises(ValueError, match="justification"):
            CorsPolicy.disabled(reason=bad)


def test_cors_allow_builds_an_enabled_allowlist() -> None:
    cors = CorsPolicy.allow(["http://a"], allow_credentials=True)
    assert cors.configured is True
    assert cors.enabled is True
    assert cors.allow_origins == ("http://a",)
    with pytest.raises(ValueError, match="at least one origin"):
        CorsPolicy.allow([])


def test_cors_wildcard_is_flagged_and_credentials_forbidden() -> None:
    wildcard = CorsPolicy.allow(["*"])
    assert wildcard.is_wildcard is True
    assert wildcard.enabled is True
    with pytest.raises(ValueError, match="credentials"):
        CorsPolicy.allow(["*"], allow_credentials=True)


def test_rate_limit_enable_disable_and_window() -> None:
    assert RateLimit().enabled is True
    assert RateLimit.disabled().enabled is False
    with pytest.raises(ValueError, match="window"):
        RateLimit(window_seconds=0)


def test_security_config_validates_construction() -> None:
    with pytest.raises(ValueError, match="max_request_bytes"):
        SecurityConfig(max_request_bytes=0)
    with pytest.raises(ValueError, match="request_id_header"):
        SecurityConfig(request_id_header="   ")
    with pytest.raises(ValueError, match="trusted_proxy_hops"):
        SecurityConfig(trusted_proxy_hops=-1)


def test_production_problems_flags_unset_cors() -> None:
    problems = SecurityConfig.default().production_problems()
    assert len(problems) == 1
    assert "CORS is unset" in problems[0]


def test_production_problems_flags_wildcard_and_disabled_rate_limit() -> None:
    config = SecurityConfig(cors=CorsPolicy.allow(["*"]), rate_limit=RateLimit.disabled())
    joined = " ".join(config.production_problems())
    assert "must not allow '*'" in joined
    assert "rate limiting must be enabled" in joined


def test_production_problems_empty_when_safe() -> None:
    config = SecurityConfig(cors=CorsPolicy.disabled(reason="api only"))
    assert config.production_problems() == []


# --------------------------------------------------------------------------- #
# structured logging: request-id context + PII redaction
# --------------------------------------------------------------------------- #
def test_get_request_id_reflects_context() -> None:
    assert get_request_id() is None
    token = request_id_ctx.set("abc-123")
    try:
        assert get_request_id() == "abc-123"
    finally:
        request_id_ctx.reset(token)


def test_redacting_filter_scrubs_message_and_args() -> None:
    filt = RedactingFilter()
    record = logging.LogRecord(
        "svc", logging.INFO, "p", 1,
        "called with Authorization: sk_live_abcDEF and Bearer tok.en.123",
        None, None,
    )
    filt.filter(record)
    assert "sk_live_abcDEF" not in record.msg
    assert "tok.en.123" not in record.msg
    assert record.msg.count("[REDACTED]") == 2

    dict_record = logging.LogRecord(
        "svc", logging.INFO, "p", 1, "m", {"password": "p", "ok": "v"}, None
    )
    filt.filter(dict_record)
    assert dict_record.args == {"password": "[REDACTED]", "ok": "v"}

    tuple_record = logging.LogRecord(
        "svc", logging.INFO, "p", 1, "m",
        ("Bearer xyz", {"token": "t"}, ["plain-cookie-value"], 42, ("nested",)),
        None,
    )
    filt.filter(tuple_record)
    assert tuple_record.args[0] == "Bearer [REDACTED]"
    assert tuple_record.args[1] == {"token": "[REDACTED]"}
    assert tuple_record.args[2] == ["plain-cookie-value"]
    assert tuple_record.args[3] == 42
    assert tuple_record.args[4] == ("nested",)


def test_redacting_filter_scrubs_extra_fields() -> None:
    filt = RedactingFilter()
    record = logging.LogRecord("svc", logging.INFO, "p", 1, "m", None, None)
    record.token = "sk_live_secret"  # sensitive key name -> redacted wholesale
    record.note = "Bearer abc.def"  # benign key, sensitive value -> scrubbed
    record.count = 7  # non-string, untouched
    filt.filter(record)
    assert record.token == "[REDACTED]"
    assert record.note == "Bearer [REDACTED]"
    assert record.count == 7


def test_request_context_filter_injects_request_id() -> None:
    filt = RequestContextFilter()
    record = logging.LogRecord("svc", logging.INFO, "p", 1, "m", None, None)
    filt.filter(record)
    assert record.request_id == "-"
    token = request_id_ctx.set("req-9")
    try:
        filt.filter(record)
        assert record.request_id == "req-9"
    finally:
        request_id_ctx.reset(token)


def test_structured_formatter_emits_json() -> None:
    record = logging.LogRecord("svc", logging.INFO, "p", 1, "hello %s", ("world",), None)
    record.request_id = "req-1"
    payload = json.loads(StructuredFormatter().format(record))
    assert payload == {
        "level": "INFO",
        "logger": "svc",
        "request_id": "req-1",
        "message": "hello world",
    }


def test_structured_formatter_includes_exception_and_defaults_request_id() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        record = logging.LogRecord("svc", logging.ERROR, "p", 1, "oops", None, sys.exc_info())
    payload = json.loads(StructuredFormatter().format(record))
    assert payload["request_id"] == "-"
    assert "ValueError" in payload["exc_info"]


def test_structured_formatter_emits_extra_fields() -> None:
    # Application ``extra=`` context (e.g. the audit log-only sink's fields) must
    # survive to the JSON line instead of being silently dropped.
    record = logging.LogRecord("svc", logging.INFO, "p", 1, "audit_event", None, None)
    record.request_id = "req-2"
    record.audit_action = "deleted"
    record.audit_target_type = "Note"
    payload = json.loads(StructuredFormatter().format(record))
    assert payload["extra"] == {"audit_action": "deleted", "audit_target_type": "Note"}


def test_structured_formatter_extra_stays_redacted() -> None:
    # The formatter renders whatever survives the handler's RedactingFilter, so a
    # secret-bearing extra is masked before it ever reaches the log line.
    record = logging.LogRecord("svc", logging.INFO, "p", 1, "login", None, None)
    record.password = "hunter2"  # noqa: S105 - deliberately fake secret under test
    RedactingFilter().filter(record)
    rendered = StructuredFormatter().format(record)
    assert "hunter2" not in rendered
    assert json.loads(rendered)["extra"] == {"password": _REDACTED}


def test_configure_logging_installs_filters_and_handler_when_none() -> None:
    logger = logging.getLogger("terp.test.logging.fresh")
    logger.handlers.clear()
    logger.filters.clear()
    configure_logging(logger=logger)
    assert any(isinstance(f, RedactingFilter) for f in logger.filters)
    assert any(isinstance(f, RequestContextFilter) for f in logger.filters)
    assert len(logger.handlers) == 1
    # Idempotent: a second call duplicates nothing.
    configure_logging(logger=logger)
    assert sum(isinstance(f, RedactingFilter) for f in logger.filters) == 1
    assert sum(isinstance(f, RequestContextFilter) for f in logger.filters) == 1
    assert len(logger.handlers) == 1


def test_configure_logging_attaches_to_existing_handler() -> None:
    logger = logging.getLogger("terp.test.logging.existing")
    logger.handlers.clear()
    logger.filters.clear()
    handler = logging.StreamHandler()
    logger.addHandler(handler)
    configure_logging(logger=logger)
    assert len(logger.handlers) == 1  # no extra handler added
    # Redaction + request-context + structured rendering land on the handler, so a
    # child logger's records cannot bypass redaction through it.
    assert any(isinstance(f, RequestContextFilter) for f in handler.filters)
    assert any(isinstance(f, RedactingFilter) for f in handler.filters)
    assert isinstance(handler.formatter, StructuredFormatter)
    configure_logging(logger=logger)  # idempotent
    assert sum(isinstance(f, RequestContextFilter) for f in handler.filters) == 1
    assert sum(isinstance(f, RedactingFilter) for f in handler.filters) == 1


def test_configure_logging_redacts_child_logger_through_handler() -> None:
    logger = logging.getLogger("terp.test.logging.redact")
    logger.handlers.clear()
    logger.filters.clear()
    logger.propagate = False
    stream = io.StringIO()
    logger.addHandler(logging.StreamHandler(stream))
    configure_logging(logger=logger)
    # A *child* logger (no handlers of its own) propagates to the protected handler.
    logging.getLogger("terp.test.logging.redact.child").error("auth=%s", "Bearer sk_live_leak")
    output = stream.getvalue()
    assert "sk_live_leak" not in output
    assert "[REDACTED]" in output


# --------------------------------------------------------------------------- #
# middleware units
# --------------------------------------------------------------------------- #
def test_security_headers_middleware_sets_headers() -> None:
    app = _starlette_app()
    app.add_middleware(SecurityHeadersMiddleware, headers=SecurityHeaders(), include_hsts=False)
    response = TestClient(app).get("/")
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "Strict-Transport-Security" not in response.headers

    hsts_app = _starlette_app()
    hsts_app.add_middleware(
        SecurityHeadersMiddleware, headers=SecurityHeaders(), include_hsts=True
    )
    assert "Strict-Transport-Security" in TestClient(hsts_app).get("/").headers


def test_request_id_middleware_generates_and_honours_inbound() -> None:
    app = _starlette_app()
    app.add_middleware(RequestIdMiddleware, header_name="X-Request-ID")
    client = TestClient(app)
    generated = client.get("/")
    assert generated.headers["X-Request-ID"]
    echoed = client.get("/", headers={"X-Request-ID": "abc-123"})
    assert echoed.headers["X-Request-ID"] == "abc-123"


def test_request_id_middleware_replaces_a_malformed_inbound_id() -> None:
    # An inbound id outside the strict length/charset shape is never echoed —
    # it would otherwise flow verbatim into logs and headers (log injection).
    app = _starlette_app()
    app.add_middleware(RequestIdMiddleware, header_name="X-Request-ID")
    client = TestClient(app)
    injected = client.get("/", headers={"X-Request-ID": "evil\ninjected: header"})
    assert injected.headers["X-Request-ID"] != "evil\ninjected: header"
    too_long = client.get("/", headers={"X-Request-ID": "a" * 200})
    assert too_long.headers["X-Request-ID"] != "a" * 200
    assert len(too_long.headers["X-Request-ID"]) == 32  # a fresh uuid4 hex


def test_rate_limit_key_uses_client_host_or_anonymous() -> None:
    with_client = Request({"type": "http", "client": ("1.2.3.4", 5), "headers": []})
    assert _rate_limit_key(with_client) == "1.2.3.4"
    no_client = Request({"type": "http", "client": None, "headers": []})
    assert _rate_limit_key(no_client) == "anonymous"


def test_rate_limit_key_prefers_the_resolved_client_ip() -> None:
    # ClientIpMiddleware stashes the trusted-proxy-resolved address on
    # request.state; the rate-limit key must use it, so a proxied deployment
    # limits the real caller instead of collapsing everyone onto the proxy IP.
    request = Request(
        {
            "type": "http",
            "client": ("10.0.0.1", 5),
            "headers": [],
            "state": {"client_ip": "203.0.113.7"},
        }
    )
    assert _rate_limit_key(request) == "203.0.113.7"


def test_forwarded_client_ip_takes_the_trusted_hop_and_fails_toward_the_peer() -> None:
    def _req(xff: str | None) -> Request:
        headers = [] if xff is None else [(b"x-forwarded-for", xff.encode())]
        return Request({"type": "http", "client": ("10.0.0.1", 5), "headers": headers})

    # One trusted hop: the last entry is the address our proxy saw.
    assert _forwarded_client_ip(_req("198.51.100.9"), trusted_hops=1) == "198.51.100.9"
    # A client-prefixed chain: only the trusted tail counts, never the client's spoof.
    assert _forwarded_client_ip(_req("6.6.6.6, 198.51.100.9"), trusted_hops=1) == "198.51.100.9"
    assert (
        _forwarded_client_ip(_req("6.6.6.6, 198.51.100.9"), trusted_hops=2) == "6.6.6.6"
    )
    # Unresolvable shapes fall back (None → the direct peer): absent header,
    # fewer entries than trusted hops, or a non-IP entry.
    assert _forwarded_client_ip(_req(None), trusted_hops=1) is None
    assert _forwarded_client_ip(_req("198.51.100.9"), trusted_hops=2) is None
    assert _forwarded_client_ip(_req("not-an-ip"), trusted_hops=1) is None


def test_client_ip_middleware_ignores_forwarding_without_a_trust_declaration() -> None:
    # hops=0 (the default): X-Forwarded-For is attacker-supplied and ignored.
    seen: list[str] = []

    async def _record(request: Request) -> PlainTextResponse:
        from terp.core import client_ip

        seen.append(client_ip(request))
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/", _record)])
    app.add_middleware(ClientIpMiddleware, trusted_proxy_hops=0)
    TestClient(app).get("/", headers={"X-Forwarded-For": "6.6.6.6"})
    assert seen == ["testclient"]


def test_client_ip_middleware_resolves_through_declared_proxy_hops() -> None:
    seen: list[str] = []

    async def _record(request: Request) -> PlainTextResponse:
        from terp.core import client_ip

        seen.append(client_ip(request))
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/", _record)])
    app.add_middleware(ClientIpMiddleware, trusted_proxy_hops=1)
    client = TestClient(app)
    client.get("/", headers={"X-Forwarded-For": "203.0.113.7"})
    client.get("/", headers={"X-Forwarded-For": "spoofed-junk"})  # unresolvable → peer
    client.get("/")  # no header → peer
    assert seen == ["203.0.113.7", "testclient", "testclient"]


def test_client_ip_helper_falls_back_without_the_middleware() -> None:
    from terp.core import client_ip

    bare = Request({"type": "http", "client": ("1.2.3.4", 5), "headers": []})
    assert client_ip(bare) == "1.2.3.4"
    no_client = Request({"type": "http", "client": None, "headers": []})
    assert client_ip(no_client) == "anonymous"


def test_client_ip_middleware_handles_a_missing_peer() -> None:
    async def _asgi_ok(scope, receive, send):  # type: ignore[no-untyped-def]
        response = PlainTextResponse("ok")
        await response(scope, receive, send)

    middleware = ClientIpMiddleware(_asgi_ok, trusted_proxy_hops=0)

    async def _receive():  # type: ignore[no-untyped-def]
        return {"type": "http.request", "body": b""}

    sent: list[dict] = []

    async def _send(message):  # type: ignore[no-untyped-def]
        sent.append(message)

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [],
        "client": None,
        "state": {},
    }
    asyncio.run(middleware(scope, _receive, _send))
    assert scope["state"]["client_ip"] == "anonymous"


def test_fixed_window_counter_blocks_then_resets() -> None:
    ticks = iter([0.0, 0.0, 100.0])
    store = InMemoryThrottleStore(clock=lambda: next(ticks))
    count, _ = store.hit("k", 60)
    assert count == 1
    blocked, reset = store.hit("k", 60)
    assert blocked == 2 and reset >= 1  # same window
    recovered, _ = store.hit("k", 60)
    assert recovered == 1  # the window elapsed → the bucket reset


def test_rate_limit_middleware_blocks_after_limit() -> None:
    app = _starlette_app()
    app.add_middleware(RateLimitMiddleware, limit=1, window=60)
    client = TestClient(app)
    first = client.get("/")
    assert first.status_code == 200
    assert first.headers["X-RateLimit-Remaining"] == "0"
    blocked = client.get("/")
    assert blocked.status_code == 429
    assert blocked.headers["Retry-After"]
    assert blocked.json()["code"] == "rate_limited"


def test_declared_length_parses_header() -> None:
    assert _declared_length({"headers": [(b"content-length", b"42")]}) == 42
    assert _declared_length({"headers": [(b"content-length", b"abc")]}) is None
    assert _declared_length({"headers": []}) is None


def test_request_size_limit_rejects_large_declared_body() -> None:
    app = _starlette_app()
    app.add_middleware(RequestSizeLimitMiddleware, max_bytes=10)
    response = TestClient(app).post("/", content=b"x" * 50)
    assert response.status_code == 413
    assert response.json()["code"] == "request_too_large"


def test_request_size_limit_allows_small_body() -> None:
    app = _starlette_app()
    app.add_middleware(RequestSizeLimitMiddleware, max_bytes=100)
    assert TestClient(app).post("/", content=b"hi").status_code == 200


def _override_probe_app() -> Starlette:
    """A two-path app for the per-prefix override tests (ADR 0067)."""
    return Starlette(
        routes=[
            Route("/api/v1/files/", _ok, methods=["POST"]),
            Route("/api/v1/notes/", _ok, methods=["POST"]),
        ]
    )


def test_request_size_override_lifts_the_cap_for_its_prefix_only() -> None:
    app = _override_probe_app()
    app.add_middleware(
        RequestSizeLimitMiddleware, max_bytes=10, overrides={"/api/v1/files": 100}
    )
    client = TestClient(app)
    body = b"x" * 50  # over the global cap, under the files allowance
    assert client.post("/api/v1/files/", content=body).status_code == 200
    refused = client.post("/api/v1/notes/", content=body)
    assert refused.status_code == 413  # every other prefix keeps the global cap
    assert refused.json()["code"] == "request_too_large"


def test_request_size_override_matches_whole_path_segments_only() -> None:
    """A prefix must not leak its allowance to a lookalike sibling (/files-evil)."""
    app = Starlette(routes=[Route("/api/v1/files-evil/", _ok, methods=["POST"])])
    app.add_middleware(
        RequestSizeLimitMiddleware, max_bytes=10, overrides={"/api/v1/files": 100}
    )
    response = TestClient(app).post("/api/v1/files-evil/", content=b"x" * 50)
    assert response.status_code == 413


def test_request_size_override_longest_prefix_wins() -> None:
    middleware = RequestSizeLimitMiddleware(
        _starlette_app(),
        max_bytes=10,
        overrides={"/api/v1/files": 100, "/api/v1/files/bulk": 200},
    )
    assert middleware._cap_for("/api/v1/files/bulk/upload") == 200
    assert middleware._cap_for("/api/v1/files/abc") == 100
    assert middleware._cap_for("/api/v1/files") == 100
    assert middleware._cap_for("/api/v1/notes/") == 10


def test_request_size_limit_passes_through_non_http_scope() -> None:
    seen: list[str] = []

    async def inner(scope: dict, receive: object, send: object) -> None:
        seen.append(scope["type"])

    middleware = RequestSizeLimitMiddleware(inner, max_bytes=10)

    async def drive() -> None:
        async def receive() -> dict:
            return {"type": "lifespan.startup"}

        async def send(_message: dict) -> None:
            return None

        await middleware({"type": "lifespan"}, receive, send)

    asyncio.run(drive())
    assert seen == ["lifespan"]


def test_request_size_limit_drops_unbounded_stream() -> None:
    received: list[dict] = []

    async def inner(scope: dict, receive, send) -> None:  # type: ignore[no-untyped-def]
        message = await receive()
        received.append(message)

    middleware = RequestSizeLimitMiddleware(inner, max_bytes=4)
    chunks = iter([{"type": "http.request", "body": b"xxxxx", "more_body": False}])

    async def drive() -> None:
        async def receive() -> dict:
            try:
                return next(chunks)
            except StopIteration:
                return {"type": "http.disconnect"}

        async def send(_message: dict) -> None:
            return None

        # No content-length header → streaming path → over-limit → disconnect.
        await middleware({"type": "http", "headers": []}, receive, send)

    asyncio.run(drive())
    assert received[-1]["type"] == "http.disconnect"


# --------------------------------------------------------------------------- #
# create_app: installs the stack, refuses unsafe production config
# --------------------------------------------------------------------------- #
def test_create_app_installs_the_security_stack() -> None:
    client = TestClient(_probe_app(SecurityConfig.default()))
    response = client.get("/api/v1/probe/ping")
    assert response.status_code == 200
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Request-ID"]
    assert response.headers["X-RateLimit-Limit"] == "240"


def test_create_app_adds_cors_when_configured() -> None:
    client = TestClient(_probe_app(SecurityConfig(cors=CorsPolicy.allow(["http://example.com"]))))
    preflight = client.options(
        "/api/v1/probe/ping",
        headers={
            "Origin": "http://example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert preflight.headers.get("access-control-allow-origin") == "http://example.com"
    # Request-id + security headers wrap CORS, so even the preflight carries them.
    assert preflight.headers["X-Request-ID"]
    assert preflight.headers["X-Frame-Options"] == "DENY"


def test_create_app_omits_cors_and_rate_limit_when_unconfigured() -> None:
    security = SecurityConfig(
        cors=CorsPolicy.disabled(reason="api only"), rate_limit=RateLimit.disabled()
    )
    response = TestClient(_probe_app(security)).get(
        "/api/v1/probe/ping", headers={"Origin": "http://example.com"}
    )
    assert "access-control-allow-origin" not in response.headers
    assert "X-RateLimit-Limit" not in response.headers


def test_create_app_refuses_unset_cors_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    plane = ControlPlane(security=SecurityConfig.default())
    with pytest.raises(BootError, match="CORS is unset"):
        create_app([ModuleSpec(name="ok", policy=Policy.default())], control_plane=plane)


def test_create_app_boots_in_production_with_explicit_security(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    plane = ControlPlane(
        security=SecurityConfig(cors=CorsPolicy.disabled(reason="api only")),
        audit=AuditPolicy.disabled(reason="trail not required for this service"),
    )
    app = create_app([ModuleSpec(name="ok", policy=Policy.default())], control_plane=plane)
    assert app.title == "Terp app"


def test_create_app_refuses_enabled_audit_without_a_sink_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Security is explicitly safe, but audit is on with only the log-only fallback:
    # production must persist its trail, so boot fails closed.
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    plane = ControlPlane(security=SecurityConfig(cors=CorsPolicy.disabled(reason="api only")))
    with pytest.raises(BootError, match="durable audit sink"):
        create_app([ModuleSpec(name="ok", policy=Policy.default())], control_plane=plane)


def test_create_app_boots_in_production_with_a_durable_audit_sink(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    plane = ControlPlane(security=SecurityConfig(cors=CorsPolicy.disabled(reason="api only")))
    app = create_app(
        [ModuleSpec(name="ok", policy=Policy.default())],
        control_plane=plane,
        audit_sink=persist_audit,
    )
    assert app.title == "Terp app"


def test_create_app_refuses_an_unmarked_audit_sink_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    plane = ControlPlane(security=SecurityConfig(cors=CorsPolicy.disabled(reason="api only")))
    with pytest.raises(BootError, match="marked durable audit sink"):
        create_app(
            [ModuleSpec(name="ok", policy=Policy.default())],
            control_plane=plane,
            audit_sink=lambda _session, _record, _policy: None,
        )


def test_error_handler_falls_back_to_a_request_id_without_middleware() -> None:
    # A bare app (no request-id middleware) still gets a request_id in the envelope,
    # exercising the get_request_id()/uuid fallback in register_error_handlers.
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/boom")
    def boom() -> None:
        raise NotFoundError("nope")

    response = TestClient(app).get("/boom")
    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "not_found"
    assert body["request_id"]


def test_unexpected_exception_renders_a_500_envelope() -> None:
    router = APIRouter()

    @router.get("/kaboom")
    def kaboom() -> dict:
        raise RuntimeError("secret-internal-detail")

    app = create_app(
        [ModuleSpec(name="probe", router=router, policy=Policy.public(reason="probe route"))],
        control_plane=ControlPlane(security=SecurityConfig.default()),
    )
    response = TestClient(app, raise_server_exceptions=False).get("/api/v1/probe/kaboom")
    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "internal_error"
    assert body["detail"] == "An unexpected error occurred."
    assert body["request_id"]
    # The raw exception detail must never leak to the client.
    assert "secret-internal-detail" not in response.text
