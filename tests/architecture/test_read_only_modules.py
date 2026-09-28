"""A module declared ``read_only`` cannot mount a route that could write (ADR 0161).

Before the declaration an authenticated module that only served reads was read-only only
because nobody had added a write route yet. The substitute an app reaches for — a test that
walks ``router.routes`` and fails on any method but ``GET`` — misses a route on an included
sub-router, because FastAPI keeps that as a nested ``_IncludedRouter`` rather than flattening
it. So the cases below are the ones a hand-written scan gets wrong, and every refusal is
driven through ``create_app``, where the declaration is enforced.
"""

from __future__ import annotations

import pytest
from fastapi import APIRouter, WebSocket
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Mount

from terp.core import BaseSchema, BootError, ModuleSpec, Policy, create_app, read_only, route_policy


class Found(BaseSchema):
    count: int


def _compose(router: APIRouter, *, declared: bool = True) -> None:
    create_app([ModuleSpec(name="reports", router=router, policy=Policy.default(), read_only=declared)])


def _reads() -> APIRouter:
    router = APIRouter()

    @router.get("/", response_model=Found)
    def count() -> Found:
        return Found(count=0)

    return router


def test_a_module_that_only_reads_boots() -> None:
    _compose(_reads())


def test_a_write_route_is_refused_and_the_refusal_names_it() -> None:
    router = _reads()

    @router.post("/", response_model=Found)
    def record() -> Found:
        return Found(count=1)

    with pytest.raises(BootError) as refused:
        _compose(router)
    message = str(refused.value)
    assert "module 'reports' is declared read_only" in message
    assert "route '/' (record) serves POST" in message
    assert "@read_only" in message


def test_a_write_route_on_an_included_sub_router_is_refused() -> None:
    """The case a scan of ``router.routes`` misses: the DELETE lives one router down.

    The path in the refusal is relative to the sub-router, so the handler's name is what
    says which route it is.
    """
    nested = APIRouter()

    @nested.delete("/{name}", status_code=204)
    def forget(name: str) -> None: ...

    router = _reads()
    router.include_router(nested, prefix="/saved")
    with pytest.raises(BootError, match=r"route '/\{name\}' \(forget\) serves DELETE"):
        _compose(router)


def test_one_mutating_method_among_several_is_enough() -> None:
    router = _reads()
    router.add_api_route(
        "/either", lambda: Found(count=0), methods=["GET", "PUT"], response_model=Found
    )
    with pytest.raises(BootError, match=r"route '/either' \(<lambda>\) serves PUT"):
        _compose(router)


def test_a_websocket_is_refused_unless_it_declares_itself_pure() -> None:
    """A WebSocket has no method after the upgrade, and the guard treats it as a write."""
    router = _reads()

    @router.websocket("/live")
    async def live(websocket: WebSocket) -> None: ...

    with pytest.raises(BootError, match=r"route '/live' \(live\) serves a WebSocket"):
        _compose(router)


async def _plain(request: Request) -> PlainTextResponse:
    return PlainTextResponse("reached")


def test_a_plain_starlette_route_is_refused_because_nothing_guards_it() -> None:
    """``add_route`` registers a route FastAPI serves without the router's dependencies.

    Measured before this check existed: in a module behind ``Policy.default()`` such a POST
    answered 200 to a request with no token, so neither the guard nor the read-only binder
    ran. A read-only module that booted with one would be promising what nothing enforces.
    """
    router = _reads()
    router.add_route("/raw", _plain, methods=["POST"])
    with pytest.raises(BootError, match=r"mounts Route '/raw', which FastAPI serves without"):
        _compose(router)


def test_a_mount_is_refused_one_router_down_too() -> None:
    nested = APIRouter()
    nested.routes.append(Mount("/sub", app=Starlette()))
    router = _reads()
    router.include_router(nested, prefix="/deeper")
    with pytest.raises(BootError, match=r"mounts Mount '/sub'"):
        _compose(router)


def test_a_route_declared_pure_boots_whatever_its_transport() -> None:
    """``@read_only`` is the runtime binder's own test, so the declaration accepts it."""
    router = _reads()

    @router.post("/preview", response_model=Found)
    @read_only
    def preview() -> Found:
        return Found(count=2)

    @router.websocket("/live")
    @read_only
    async def live(websocket: WebSocket) -> None: ...

    _compose(router)


def test_a_route_policy_does_not_reopen_writes() -> None:
    """A route's own policy says who may call; it cannot undo what the module said it does."""
    router = _reads()

    @router.post("/", response_model=Found)
    @route_policy(Policy.default())
    def record() -> Found:
        return Found(count=1)

    with pytest.raises(BootError, match=r"route '/' \(record\) serves POST"):
        _compose(router)


def test_the_same_write_route_boots_in_a_module_that_did_not_declare_it() -> None:
    """The refusal is the declaration's, not a new default for every module."""
    router = _reads()

    @router.post("/", response_model=Found)
    def record() -> Found:
        return Found(count=1)

    _compose(router, declared=False)
