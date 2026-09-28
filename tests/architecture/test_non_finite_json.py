"""A JSON body carrying a non-finite number is refused at the boundary (ADR 0152).

JSON has no non-finite numbers, and Python's decoder produces them anyway: from the
constants ``NaN`` / ``Infinity`` / ``-Infinity``, which it accepts though JSON does not
have them, and from a legal literal too large for a double, ``1e400``, which it reads as
infinity. Before this control a non-finite value sent to a constrained field was a 500 (the
validation error quoted the value back and could not be encoded), one sent to a plain
``float`` field was *accepted*, and one nested in a ``dict[str, Any]`` reached the service
untouched. The full-stack tests below drive ``create_app`` so they fail if the middleware is
not installed; the unit tests pin the edges of what the middleware reads and what it leaves
alone.
"""

from __future__ import annotations

import asyncio
import json
import math
from typing import Any

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient
from pydantic import Field
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from terp.core import BaseSchema, ControlPlane, ModuleSpec, Policy, create_app, route_policy
from terp.core._internal.middleware import NonFiniteJsonMiddleware, _non_finite_number

_URL = "/api/v1/measure/"
_JSON = {"content-type": "application/json"}


class Measurement(BaseSchema):
    amount: float
    limit: float = Field(default=1.0, gt=0)
    label: str = Field(default="", max_length=100)
    details: dict[str, Any] = Field(default_factory=dict)


class Verdict(BaseSchema):
    finite: bool
    label: str = Field(max_length=100)


def _client() -> TestClient:
    router = APIRouter()

    @router.post("/", response_model=Verdict)
    @route_policy(Policy.public_write(reason="a fixture that probes this route without a token"))
    def measure(body: Measurement) -> Verdict:
        values = [body.amount, body.limit, *body.details.values()]
        return Verdict(
            finite=all(math.isfinite(v) for v in values if isinstance(v, float)),
            label=body.label,
        )

    app = create_app(
        [ModuleSpec(name="measure", router=router, policy=Policy.public_write(reason="probe"))],
        control_plane=ControlPlane(),
    )
    return TestClient(app, raise_server_exceptions=False)


def _assert_refused(response: Any, constant: str) -> None:
    assert response.status_code == 422, response.text
    body = response.json()
    assert body["code"] == "non_finite_number"
    assert f"contains {constant}," in body["detail"]
    assert body["request_id"]


# --------------------------------------------------------------------------- #
# Through the composed app: the three ways a non-finite number used to get in
# --------------------------------------------------------------------------- #
def test_nan_in_a_constrained_field_is_a_422_not_a_500() -> None:
    response = _client().post(_URL, content=b'{"amount": 1, "limit": NaN}', headers=_JSON)
    _assert_refused(response, "NaN")


def test_infinity_in_a_plain_float_field_is_refused_not_accepted() -> None:
    response = _client().post(_URL, content=b'{"amount": Infinity}', headers=_JSON)
    _assert_refused(response, "Infinity")


def test_negative_infinity_nested_in_an_untyped_mapping_is_refused() -> None:
    response = _client().post(
        _URL, content=b'{"amount": 1, "details": {"floor": -Infinity}}', headers=_JSON
    )
    _assert_refused(response, "-Infinity")


# --------------------------------------------------------------------------- #
# Through the composed app: the same value, written as a number too large
# --------------------------------------------------------------------------- #
def test_an_overflowing_literal_in_a_plain_float_field_is_refused_not_accepted() -> None:
    """``1e400`` is a legal JSON number the decoder reads as infinity — no constant at all."""
    response = _client().post(_URL, content=b'{"amount": 1e400}', headers=_JSON)
    _assert_refused(response, "1e400")


def test_an_overflowing_literal_in_a_constrained_field_is_a_422_not_a_500() -> None:
    """``gt=0`` refuses ``-inf`` and quotes it back, which is the renderer's 500."""
    response = _client().post(
        _URL, content=b'{"amount": 1, "limit": -1e400}', headers=_JSON
    )
    _assert_refused(response, "-1e400")


def test_an_overflowing_literal_nested_in_an_untyped_mapping_is_refused() -> None:
    response = _client().post(
        _URL, content=b'{"amount": 1, "details": {"ceiling": 1.5E+999}}', headers=_JSON
    )
    _assert_refused(response, "1.5E+999")


def test_a_long_overflowing_literal_is_not_quoted_back_whole() -> None:
    """The body cap bounds a literal only at the size of the body; the detail stays short."""
    literal = "9" * 400 + ".0"
    response = _client().post(
        _URL, content=f'{{"amount": {literal}}}'.encode(), headers=_JSON
    )
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert f"contains {'9' * 24}…, a number too large to represent." in detail
    assert literal not in detail


def test_a_huge_integer_is_left_to_the_field_and_is_a_422() -> None:
    """An integer literal decodes exactly, so it cannot overflow in the decoder.

    pydantic refuses one too large for a ``float`` field and quotes the ``int`` back, which
    encodes — the reason the middleware need not look at integers at all.
    """
    response = _client().post(
        _URL, content=('{"amount": 1' + "0" * 400 + "}").encode(), headers=_JSON
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"][0]["type"] == "float_type"


def test_a_finite_body_still_reaches_the_handler() -> None:
    response = _client().post(_URL, json={"amount": 2.5, "details": {"x": 1.0}})
    assert response.status_code == 200
    assert response.json() == {"finite": True, "label": ""}


def test_the_words_inside_a_string_are_not_numbers() -> None:
    """A byte scan for ``NaN`` would refuse this body; the strict parse must not."""
    response = _client().post(
        _URL, json={"amount": 1, "label": "NaN, Infinity and -Infinity are words here"}
    )
    assert response.status_code == 200
    assert response.json()["label"] == "NaN, Infinity and -Infinity are words here"


def test_a_utf16_body_is_refused_as_well() -> None:
    """The decoder accepts UTF-16 JSON, so a check that only scans bytes would miss it."""
    client = _client()
    accepted = client.post(
        _URL, content='{"amount": 3}'.encode("utf-16"), headers=_JSON
    )
    assert accepted.status_code == 200  # the decoder really does take this encoding
    refused = client.post(_URL, content='{"amount": NaN}'.encode("utf-16"), headers=_JSON)
    _assert_refused(refused, "NaN")


def test_a_structured_json_media_type_is_refused_too() -> None:
    """FastAPI decodes ``application/*+json`` as JSON, so the refusal covers it."""
    response = _client().post(
        _URL,
        content=b'{"amount": NaN}',
        headers={"content-type": "application/merge-patch+json; charset=utf-8"},
    )
    _assert_refused(response, "NaN")


def test_malformed_json_keeps_fastapis_own_answer() -> None:
    response = _client().post(_URL, content=b'{"amount": ', headers=_JSON)
    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "json_invalid"


# --------------------------------------------------------------------------- #
# The middleware on its own: what it reads, and what it leaves alone
# --------------------------------------------------------------------------- #
async def _echo(request: Request) -> PlainTextResponse:
    return PlainTextResponse((await request.body()).decode("latin-1"))


def _bare_client() -> TestClient:
    app = Starlette(routes=[Route("/", _echo, methods=["POST"])])
    app.add_middleware(NonFiniteJsonMiddleware)
    return TestClient(app)


def test_a_body_not_declared_as_json_is_not_read() -> None:
    client = _bare_client()
    plain = client.post("/", content=b"NaN", headers={"content-type": "text/plain"})
    assert (plain.status_code, plain.text) == (200, "NaN")
    undeclared = client.post("/", content=b"NaN")
    assert (undeclared.status_code, undeclared.text) == (200, "NaN")


def test_a_constant_split_across_chunks_is_still_found() -> None:
    def chunks():  # type: ignore[no-untyped-def]
        yield b'{"amount": Na'
        yield b"N}"

    response = _bare_client().post("/", content=chunks(), headers=_JSON)
    assert response.status_code == 422
    assert response.json()["code"] == "non_finite_number"


def test_the_replayed_body_is_what_the_client_sent() -> None:
    body = b'{"amount": 1.5}'
    response = _bare_client().post("/", content=body, headers=_JSON)
    assert (response.status_code, response.text) == (200, body.decode())


def test_a_client_gone_mid_body_is_handed_on_unjudged() -> None:
    """A partial body is not answered, even one that already spells ``NaN``."""
    received: list[dict] = []

    async def inner(scope: dict, receive, send) -> None:  # type: ignore[no-untyped-def]
        received.append(await receive())
        received.append(await receive())

    middleware = NonFiniteJsonMiddleware(inner)
    messages = iter(
        [
            {"type": "http.request", "body": b'{"amount": NaN', "more_body": True},
            {"type": "http.disconnect"},
        ]
    )
    sent: list[dict] = []

    async def drive() -> None:
        async def receive() -> dict:
            return next(messages)

        async def send(message: dict) -> None:
            sent.append(message)

        await middleware(
            {"type": "http", "headers": [(b"content-type", b"application/json")]},
            receive,
            send,
        )

    asyncio.run(drive())
    assert sent == []
    assert [m["type"] for m in received] == ["http.request", "http.disconnect"]


def test_a_non_http_scope_passes_straight_through() -> None:
    seen: list[str] = []

    async def inner(scope: dict, receive: object, send: object) -> None:
        seen.append(scope["type"])

    async def drive() -> None:
        async def receive() -> dict:
            return {"type": "lifespan.startup"}

        async def send(_message: dict) -> None:
            return None

        await NonFiniteJsonMiddleware(inner)({"type": "lifespan"}, receive, send)

    asyncio.run(drive())
    assert seen == ["lifespan"]


def test_only_non_finite_numbers_are_reported() -> None:
    assert _non_finite_number(b"[1, NaN]") == "NaN, which is not a JSON number"
    assert _non_finite_number(b'{"a": -Infinity}') == "-Infinity, which is not a JSON number"
    assert _non_finite_number(b"[2.5, 1e400]") == "1e400, a number too large to represent"
    assert _non_finite_number(json.dumps({"a": 1.7976931348623157e308}).encode()) is None
    assert _non_finite_number(b"[1e-400]") is None  # underflows to 0.0, which is finite
    assert _non_finite_number(b"") is None  # malformed: FastAPI's to answer
    assert _non_finite_number(b"\xff\xfe\x00") is None  # undecodable: likewise


def test_a_body_nested_past_the_recursion_limit_is_left_to_fastapi(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A decoder that gives up on depth is FastAPI's to answer, not this middleware's.

    How deep that is depends on the platform's stack — a nesting that overflows on one
    runner parses on another — so the decoder is made to give up rather than a depth
    being guessed at.
    """

    def too_deep(*_args: object, **_kwargs: object) -> object:
        raise RecursionError("maximum recursion depth exceeded while decoding a JSON array")

    monkeypatch.setattr(json, "loads", too_deep)
    assert _non_finite_number(b"[[[NaN]]]") is None
