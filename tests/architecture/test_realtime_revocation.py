"""Real transport boundaries reload committed grants instead of trusting mint."""

from __future__ import annotations

import asyncio
import importlib
import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlmodel import Session, SQLModel, create_engine
from starlette.websockets import WebSocketDisconnect

from terp.capabilities.access import AccessService, enforce_permission
from terp.capabilities.realtime import (
    REALTIME_MINT_TICKET, REALTIME_SUBSCRIBE_SSE, REALTIME_SUBSCRIBE_WEBSOCKET,
    ConnectionTicket, RealtimeChannel, clear_channels, configure_broker,
    configure_realtime, configure_ticket_store, get_ticket_store, module,
    publish, register_channel, reset_realtime_configuration,
)
from terp.capabilities.realtime.router import _sse_stream, _validate_live, subscribe_sse
from terp.capabilities.realtime.transport import open_subscription
from terp.core import (
    EDITOR, AuthenticationError, ControlPlane, OperationCatalog, Permission,
    Principal, create_app, get_session,
)

router_module = importlib.import_module("terp.capabilities.realtime.router")
READ = Permission("records.read", EDITOR)
WRITE = Permission("records.command", EDITOR)


class Notice(BaseModel):
    value: str


@pytest.fixture
def live(tmp_path):
    clear_channels()
    configure_broker(None)
    configure_ticket_store(None)
    reset_realtime_configuration()
    engine = create_engine(f"sqlite:///{tmp_path / 'realtime.sqlite'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    actor = Principal(uuid.uuid4(), EDITOR)
    with Session(engine) as session:
        for permission in (READ, WRITE):
            AccessService().grant(session, actor.id, permission.name)

    sessions = []
    closed = []

    def provider() -> Iterator[Session]:
        with Session(engine) as session:
            sessions.append(session)
            try:
                yield session
            finally:
                closed.append(session)

    app = create_app(
        [module], discover_capabilities=False, principal_provider=lambda: actor,
        control_plane=ControlPlane(operations=OperationCatalog(operations=(
            REALTIME_MINT_TICKET, REALTIME_SUBSCRIBE_SSE, REALTIME_SUBSCRIBE_WEBSOCKET,
        ))),
    )
    app.dependency_overrides[get_session] = provider
    configure_realtime(permission_enforcer=enforce_permission, message_session_provider=provider)
    yield engine, actor, app, sessions, closed, provider
    clear_channels()
    configure_broker(None)
    configure_ticket_store(None)
    reset_realtime_configuration()
    engine.dispose()


def _mint(client, channel):
    response = client.post("/api/v1/realtime/tickets", json={"channel": channel.name, "transport": channel.mode})
    assert response.status_code == 201, response.text
    return response.json()["ticket"]


def _revoke(engine, actor, permission=READ):
    with Session(engine) as session:
        assert AccessService().revoke(session, actor.id, permission.name)


@pytest.mark.parametrize("mode", ["sse", "websocket"])
def test_ticket_redeems_only_while_its_grant_still_exists(live, mode):
    engine, actor, app, *_ = live
    channel = register_channel(RealtimeChannel("records.changes", Notice, mode=mode, requirement=READ))
    with TestClient(app) as client:
        token = _mint(client, channel)
        _revoke(engine, actor)
        if mode == "sse":
            response = client.get(f"/api/v1/realtime/sse/{channel.name}", params={"ticket": token})
            assert response.status_code == 401
        else:
            with pytest.raises(WebSocketDisconnect) as refused:
                with client.websocket_connect(f"/api/v1/realtime/ws/{channel.name}?ticket={token}"):
                    pass
            assert refused.value.code == 1008
        # The denied redemption still consumes its ticket.
        assert get_ticket_store().consume(token, channel=channel.name, transport=mode) is None


@pytest.mark.parametrize("boundary", ["outbound", "inbound", "heartbeat", "audience", "lookup_error"])
def test_established_websocket_stops_after_current_authority_changes(live, monkeypatch, boundary):
    engine, actor, app, _, _, provider = live
    handled = []
    audience = [str(actor.id)]

    async def handler(_session, _actor, message):
        handled.append(message.value)
        await publish(channel, Notice(value="accepted"), audience=audience[0])

    channel = register_channel(RealtimeChannel(
        "records.live", Notice, mode="websocket", requirement=READ,
        inbound_requirement=WRITE, inbound_model=Notice, on_message=handler,
        audience=lambda _session, _actor: audience[0],
    ))
    if boundary == "heartbeat":
        original = router_module._websocket_liveness

        async def quick_heartbeat(socket, ticket):
            await original(socket, ticket, interval_seconds=0.01)

        monkeypatch.setattr(router_module, "_websocket_liveness", quick_heartbeat)
    with TestClient(app) as client:
        token = _mint(client, channel)
        with client.websocket_connect(f"/api/v1/realtime/ws/{channel.name}?ticket={token}") as socket:
            socket.send_json({"value": "before"})
            assert socket.receive_json() == {"value": "accepted"}
            assert handled == ["before"]
            if boundary == "audience":
                audience[0] = "another-audience"
            elif boundary == "lookup_error":
                def unavailable(*_args):
                    raise RuntimeError("authorization database unavailable")
                configure_realtime(permission_enforcer=unavailable, message_session_provider=provider)
            else:
                _revoke(engine, actor, WRITE if boundary == "inbound" else READ)
            if boundary == "inbound":
                socket.send_json({"value": "after"})
            elif boundary != "heartbeat":
                asyncio.run(publish(channel, Notice(value="must not be delivered"), audience=str(actor.id)))
            with pytest.raises(WebSocketDisconnect) as closed:
                socket.receive_json()
            assert closed.value.code == 1008
            assert handled == ["before"], "a revoked inbound grant must never reach the handler"


@pytest.mark.parametrize("boundary", ["payload", "heartbeat", "audience"])
def test_established_sse_rechecks_fresh_state_before_each_yield(live, boundary):
    engine, actor, _, sessions, closed, _ = live
    audience = [str(actor.id)]
    channel = register_channel(RealtimeChannel(
        "records.feed", Notice, requirement=READ,
        audience=lambda _session, _actor: audience[0],
    ))
    ticket = ConnectionTicket(actor, channel.name, "sse", audience=audience[0])

    async def exercise():
        messages = await open_subscription(channel.name, ticket.audience)
        stream = _sse_stream(messages, ticket, heartbeat_seconds=0.01)
        assert await anext(stream) == b": keepalive\n\n"
        if boundary == "audience":
            audience[0] = "another-audience"
        else:
            _revoke(engine, actor)
        pending = asyncio.create_task(anext(stream))
        if boundary != "heartbeat":
            await publish(channel, Notice(value="must not be delivered"), audience=ticket.audience)
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(pending, timeout=2)
        await stream.aclose()

    asyncio.run(exercise())
    assert len(sessions) >= 2
    assert len({id(session) for session in sessions}) == len(sessions)
    assert closed == sessions


def test_live_validation_refuses_missing_or_changed_channel_and_validator_errors(live):
    _, actor, _, _, _, provider = live
    channel = register_channel(RealtimeChannel("records.checked", Notice, requirement=READ))
    ticket = ConnectionTicket(actor, channel.name, "sse", audience=str(actor.id))
    assert _validate_live(ticket)
    assert not _validate_live(ConnectionTicket(actor, channel.name, "websocket", audience=str(actor.id)))
    clear_channels()
    assert not _validate_live(ticket)
    register_channel(channel)

    def broken_validator(*_args):
        raise RuntimeError("identity lookup failed")

    configure_realtime(permission_enforcer=enforce_permission, principal_validator=broken_validator, message_session_provider=provider)
    assert not _validate_live(ticket)
    token = get_ticket_store().issue(ticket, ttl_seconds=30)
    with pytest.raises(AuthenticationError):
        asyncio.run(subscribe_sse(channel.name, token))
