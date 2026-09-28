"""Every route on a module router is one the deny-by-default guard runs for (ADR 0166).

``create_app`` guards a module by mounting its router with dependencies, and FastAPI attaches
router dependencies to its own routes only. A plain Starlette route, a Starlette WebSocket
route and a mount are served without them. Measured before this refusal existed: in a module
behind ``Policy.default()``, an unauthenticated ``POST`` to a route from ``add_route`` and to a
mounted sub-application both answered 200. The first test below is that measurement, kept.
"""

from __future__ import annotations

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Mount, Route
from starlette.websockets import WebSocket

from terp.core import BaseSchema, BootError, ModuleSpec, Policy, create_app


class Found(BaseSchema):
    count: int


async def _plain(request: Request) -> PlainTextResponse:
    return PlainTextResponse("reached")


async def _socket(websocket: WebSocket) -> None: ...


def _compose(router: APIRouter) -> None:
    create_app([ModuleSpec(name="reports", router=router, policy=Policy.default())])


def _guarded() -> APIRouter:
    router = APIRouter()

    @router.get("/", response_model=Found)
    def count() -> Found:
        return Found(count=0)

    return router


def test_what_the_guard_does_not_see_is_reachable_without_a_token() -> None:
    """Why the refusal exists: the same POST, served straight from FastAPI, answers anyone.

    Composed by hand, outside ``create_app``, with the router dependency the guard is — so
    this holds FastAPI to the behaviour the refusal is written against. If FastAPI ever
    attached router dependencies to plain routes, this fails and the refusal can be revisited.
    """
    from fastapi import Depends, FastAPI, HTTPException

    def deny() -> None:
        raise HTTPException(status_code=401)

    router = _guarded()
    router.add_route("/raw", _plain, methods=["POST"])
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/reports", dependencies=[Depends(deny)])
    client = TestClient(app)
    assert client.get("/api/v1/reports/").status_code == 401  # the FastAPI route is guarded
    assert client.post("/api/v1/reports/raw").status_code == 200  # the plain one is not


def test_a_plain_starlette_route_is_refused() -> None:
    router = _guarded()
    router.add_route("/raw", _plain, methods=["POST"])
    with pytest.raises(BootError) as refused:
        _compose(router)
    message = str(refused.value)
    assert "module 'reports' mounts Route '/raw'" in message
    assert "the deny-by-default guard never runs for it" in message
    assert "add_api_route" in message


def test_a_starlette_websocket_route_is_refused() -> None:
    router = _guarded()
    router.add_websocket_route("/live", _socket)
    with pytest.raises(BootError, match=r"mounts WebSocketRoute '/live'"):
        _compose(router)


def test_a_mount_is_refused_one_router_down_too() -> None:
    """``routes.append`` is a spelling the build-time rule does not see; the boot does."""
    nested = APIRouter()
    nested.routes.append(Mount("/sub", app=Starlette(routes=[Route("/", _plain)])))
    router = _guarded()
    router.include_router(nested, prefix="/deeper")
    with pytest.raises(BootError, match=r"mounts Mount '/sub'"):
        _compose(router)


def test_a_router_of_fastapi_routes_boots_however_it_is_nested() -> None:
    nested = APIRouter()

    @nested.get("/deeper", response_model=Found)
    def deeper() -> Found:
        return Found(count=1)

    router = _guarded()
    router.include_router(nested, prefix="/sub")
    _compose(router)
