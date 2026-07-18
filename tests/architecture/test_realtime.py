"""Typed realtime capability: channels, one-use tickets, SSE and WebSocket.

The browser cannot attach the in-memory bearer header to native EventSource /
WebSocket constructors, so the capability mints a 30-second opaque ticket over
the normal authenticated client and consumes it exactly once at handshake.
These tests exercise that security boundary and the typed/backpressure paths.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlmodel import Session, SQLModel, create_engine
from sqlalchemy.pool import StaticPool
from starlette.requests import Request
from starlette.websockets import WebSocketDisconnect

from terp.capabilities.realtime import (
    BackpressureError,
    ConnectionTicket,
    InMemoryConnectionTicketStore,
    InMemoryRealtimeBroker,
    RealtimeBroker,
    RealtimeChannel,
    clear_channels,
    configure_broker,
    configure_realtime,
    configure_ticket_store,
    get_ticket_store,
    get_broker,
    get_channel,
    audience_topic,
    module,
    publish,
    register_channel,
    registered_channels,
    reset_realtime_configuration,
    global_audience,
)
from terp.capabilities import realtime as realtime_package
from terp.capabilities.realtime.router import TicketRequest, mint_ticket, subscribe_sse
from terp.capabilities.realtime.router import (
    _sse_data,
    _sse_stream,
    _settle_websocket_tasks,
    _websocket_inbound,
    _websocket_liveness,
    _websocket_outbound,
    _raise_unexpected_task_results,
    subscribe_websocket,
)
from terp.core import AuthorizationRequirement
from terp.core import (
    EDITOR,
    VIEWER,
    Permission,
    PermissionDeniedError,
    Principal,
    create_app,
    get_principal,
    get_session,
)


class Notice(BaseModel):
    sequence: int
    text: str


class Command(BaseModel):
    action: str


@pytest.fixture(autouse=True)
def _reset_realtime() -> Iterator[None]:
    clear_channels()
    configure_broker(None)
    configure_ticket_store(None)
    reset_realtime_configuration()
    yield
    clear_channels()
    configure_broker(None)
    configure_ticket_store(None)
    reset_realtime_configuration()


def _principal(role=EDITOR) -> Principal:
    return Principal(id=uuid.uuid4(), role=role)


_FAKE_BEARER = "test-access-token"  # noqa: S105 - test fixture, not a real credential


def _request(token: str = _FAKE_BEARER) -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/v1/realtime/tickets",
            "raw_path": b"/api/v1/realtime/tickets",
            "query_string": b"",
            "headers": [(b"authorization", f"Bearer {token}".encode())],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
            "root_path": "",
        }
    )


def test_channel_registry_validates_and_refuses_conflicting_declarations() -> None:
    channel = register_channel(RealtimeChannel("notes.changed", Notice))
    assert get_channel("notes.changed") == channel
    assert registered_channels() == (channel,)
    assert register_channel(channel) is channel
    with pytest.raises(ValueError, match="duplicate"):
        register_channel(RealtimeChannel("notes.changed", Notice, mode="websocket"))
    with pytest.raises(ValueError, match="lowercase"):
        RealtimeChannel("Notes Changed", Notice)
    with pytest.raises(TypeError, match="Pydantic"):
        RealtimeChannel("notes.raw", dict)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="declared together"):
        RealtimeChannel("notes.commands", Notice, mode="websocket", inbound_model=Command)
    with pytest.raises(ValueError, match="only WebSocket"):
        RealtimeChannel(
            "notes.commands",
            Notice,
            inbound_model=Command,
            on_message=lambda _session, _principal, _message: None,
        )
    with pytest.raises(ValueError, match="mode"):
        RealtimeChannel("notes.bad", Notice, mode="other")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="inbound_model"):
        RealtimeChannel(
            "notes.bad-input",
            Notice,
            mode="websocket",
            inbound_model=dict,  # type: ignore[arg-type]
            on_message=lambda _session, _principal, _message: None,
        )
    with pytest.raises(TypeError, match="audience"):
        RealtimeChannel("notes.bad-audience", Notice, audience=None)  # type: ignore[arg-type]
    explicit = AuthorizationRequirement.from_role(VIEWER)
    assert RealtimeChannel("notes.explicit", Notice, requirement=explicit).requirement is explicit


def test_realtime_public_surface_and_module_posture_are_explicit() -> None:
    assert {
        "RealtimeChannel",
        "MessageSessionProvider",
        "register_channel",
        "publish",
        "configure_realtime",
        "configure_ticket_store",
        "global_audience",
    } <= set(realtime_package.__all__)
    assert module.name == "realtime" and module.router is not None
    assert module.policy is not None and module.policy.allows_public_writes
    assert "one-use" in (module.policy.public_write_reason or "")
    assert global_audience(object(), _principal()) == "global"  # type: ignore[arg-type]


def test_ticket_store_is_exact_match_single_use_and_ttl_bounded() -> None:
    now = [10.0]
    store = InMemoryConnectionTicketStore(clock=lambda: now[0])
    ticket = ConnectionTicket(_principal(), "notes.changed", "sse")
    token = store.issue(ticket, ttl_seconds=3)
    # A mismatch burns the ticket instead of becoming an oracle.
    assert store.consume(token, channel="other", transport="sse") is None
    assert store.consume(token, channel="notes.changed", transport="sse") is None

    token = store.issue(ticket, ttl_seconds=3)
    assert store.consume(token, channel="notes.changed", transport="sse") == ticket
    assert store.consume(token, channel="notes.changed", transport="sse") is None

    token = store.issue(ticket, ttl_seconds=3)
    now[0] = 13.0
    assert store.consume(token, channel="notes.changed", transport="sse") is None
    # Issuing later sweeps expired entries before inserting the new ticket.
    stale = store.issue(ticket, ttl_seconds=1)
    now[0] = 15.0
    fresh = store.issue(ticket, ttl_seconds=2)
    assert store.consume(stale, channel="notes.changed", transport="sse") is None
    assert store.consume(fresh, channel="notes.changed", transport="sse") == ticket
    with pytest.raises(ValueError, match="positive"):
        store.issue(ticket, ttl_seconds=0)
    store.reset()


def test_lazy_realtime_defaults_are_singletons_under_concurrency() -> None:
    configure_broker(None)
    configure_ticket_store(None)
    with ThreadPoolExecutor(max_workers=8) as executor:
        brokers = tuple(executor.map(lambda _index: get_broker(), range(64)))
        stores = tuple(executor.map(lambda _index: get_ticket_store(), range(64)))
    assert all(broker is brokers[0] for broker in brokers)
    assert all(store is stores[0] for store in stores)


def test_ticket_mint_enforces_mode_role_permission_and_live_principal() -> None:
    session = object()
    viewer_channel = register_channel(RealtimeChannel("notes.changed", Notice))
    ticket = mint_ticket(
        TicketRequest(channel=viewer_channel.name, transport="sse"),
        _request(),
        session,  # type: ignore[arg-type]
        principal=_principal(VIEWER),
    )
    assert ticket.channel == viewer_channel.name and ticket.expires_in == 30
    redeemed = get_ticket_store().consume(
        ticket.ticket, channel=viewer_channel.name, transport="sse"
    )
    assert redeemed is not None and redeemed.audience == str(redeemed.principal.id)

    with pytest.raises(PermissionDeniedError):
        mint_ticket(
            TicketRequest(channel=viewer_channel.name, transport="websocket"),
            _request(),
            session,  # type: ignore[arg-type]
            principal=_principal(VIEWER),
        )

    bidirectional = register_channel(
        RealtimeChannel(
            "notes.commands",
            Notice,
            mode="websocket",
            inbound_model=Command,
            on_message=lambda _session, _principal, _message: None,
        )
    )
    with pytest.raises(PermissionDeniedError):
        mint_ticket(
            TicketRequest(channel=bidirectional.name, transport="websocket"),
            _request(),
            session,  # type: ignore[arg-type]
            principal=_principal(VIEWER),
        )
    assert mint_ticket(
        TicketRequest(channel=bidirectional.name, transport="websocket"),
        _request(),
        session,  # type: ignore[arg-type]
        principal=_principal(EDITOR),
    ).ticket

    approval = Permission("notes.watch", min_role=VIEWER)
    permission_channel = register_channel(
        RealtimeChannel(
            "notes.secure", Notice, requirement=approval
        )
    )
    with pytest.raises(PermissionDeniedError):
        mint_ticket(
            TicketRequest(channel=permission_channel.name, transport="sse"),
            _request(),
            session,  # type: ignore[arg-type]
            principal=_principal(VIEWER),
        )

    configure_realtime(
        permission_enforcer=lambda _session, _id, name: name == "notes.watch",
        principal_validator=lambda principal, credential: (
            principal.role.rank >= VIEWER.rank and credential == "test-access-token"
        ),
    )
    assert mint_ticket(
        TicketRequest(channel=permission_channel.name, transport="sse"),
        _request(),
        session,  # type: ignore[arg-type]
        principal=_principal(VIEWER),
    ).ticket
    configure_realtime(principal_validator=lambda _principal, _credential: False)
    from terp.core import AuthenticationError

    with pytest.raises(AuthenticationError):
        mint_ticket(
            TicketRequest(channel=viewer_channel.name, transport="sse"),
            _request(),
            session,  # type: ignore[arg-type]
            principal=_principal(VIEWER),
        )
    with pytest.raises(AuthenticationError):
        mint_ticket(
            TicketRequest(channel=viewer_channel.name, transport="sse"),
            _request(),
            session,  # type: ignore[arg-type]
            principal=None,
        )


def test_publish_validates_messages_and_broker_fans_out() -> None:
    channel = register_channel(RealtimeChannel("notes.changed", Notice))
    broker = InMemoryRealtimeBroker(queue_size=2)
    configure_broker(broker)

    async def exercise() -> None:
        iterator = broker.stream(audience_topic(channel.name, "user-a")).__aiter__()
        pending = asyncio.create_task(anext(iterator))
        await asyncio.sleep(0)
        await publish(channel, Notice(sequence=1, text="hello"), audience="user-a")
        assert await pending == '{"sequence":1,"text":"hello"}'
        await iterator.aclose()

    asyncio.run(exercise())
    with pytest.raises(ValueError, match="not registered"):
        asyncio.run(
            publish(
                RealtimeChannel("other", Notice),
                Notice(sequence=1, text="x"),
                audience="user-a",
            )
        )


def test_audience_topics_are_isolated_and_validated() -> None:
    assert audience_topic("notes.changed", "tenant-a") != audience_topic(
        "notes.changed", "tenant-b"
    )
    with pytest.raises(ValueError, match="non-empty"):
        audience_topic("notes.changed", "")
    with pytest.raises(ValueError, match="max 500"):
        audience_topic("notes.changed", "x" * 501)
    with pytest.raises(ValueError, match="max 500"):
        audience_topic("notes.changed", "bad\x00audience")


def test_broker_disconnects_a_slow_subscriber_on_overflow() -> None:
    broker = InMemoryRealtimeBroker(queue_size=1)

    async def exercise() -> None:
        iterator = broker.stream("notes.changed").__aiter__()
        first = asyncio.create_task(anext(iterator))
        await asyncio.sleep(0)
        await broker.publish("notes.changed", "one")
        assert await first == "one"
        await broker.publish("notes.changed", "two")
        await broker.publish("notes.changed", "three")
        await asyncio.sleep(0)
        with pytest.raises(BackpressureError):
            await anext(iterator)
        await iterator.aclose()

    asyncio.run(exercise())
    with pytest.raises(ValueError, match="positive"):
        InMemoryRealtimeBroker(queue_size=0)
    broker.reset()


class _WebSocketDouble:
    def __init__(self, messages: list[str] | None = None) -> None:
        self.messages = list(messages or [])
        self.sent: list[str] = []
        self.closed: list[tuple[int, str]] = []
        self.accepted = False

    async def receive_text(self) -> str:
        if not self.messages:
            raise WebSocketDisconnect(1000)
        return self.messages.pop(0)

    async def send_text(self, value: str) -> None:
        self.sent.append(value)

    async def close(self, *, code: int, reason: str) -> None:
        self.closed.append((code, reason))

    async def accept(self) -> None:
        self.accepted = True


class _FiniteBroker(RealtimeBroker):
    async def publish(self, channel: str, payload: str) -> None:
        del channel, payload

    def stream(self, channel: str):
        del channel

        async def values():
            yield '{"sequence":3,"text":"pushed"}'

        return values()


class _BackpressureBroker(RealtimeBroker):
    async def publish(self, channel: str, payload: str) -> None:
        del channel, payload

    def stream(self, channel: str):
        del channel

        async def values():
            if False:
                yield ""
            raise BackpressureError("slow")

        return values()


def test_sse_protocol_strips_newlines_emits_payload_and_heartbeat() -> None:
    assert _sse_data('{"text":"a\r\nb"}') == b'data: {"text":"ab"}\n\n'
    channel = register_channel(RealtimeChannel("notes.sse", Notice))
    broker = InMemoryRealtimeBroker()
    configure_broker(broker)
    principal = _principal(VIEWER)
    ticket = ConnectionTicket(
        principal,
        channel.name,
        "sse",
        credential="live",
        audience="user-a",
    )

    async def exercise() -> None:
        stream = _sse_stream(channel, ticket, heartbeat_seconds=0.001)
        heartbeat = await anext(stream)
        assert heartbeat == b": keepalive\n\n"
        pending = asyncio.create_task(anext(stream))
        await asyncio.sleep(0)
        await publish(
            channel, Notice(sequence=2, text="next"), audience="user-a"
        )
        assert await pending == b'data: {"sequence":2,"text":"next"}\n\n'
        # A second payload proves the stream re-arms its broker read after
        # yielding (a keepalive earlier must never have closed the iterator).
        pending = asyncio.create_task(anext(stream))
        await asyncio.sleep(0)
        await publish(
            channel, Notice(sequence=3, text="again"), audience="user-a"
        )
        assert await pending == b'data: {"sequence":3,"text":"again"}\n\n'
        await stream.aclose()

    asyncio.run(exercise())

    configure_broker(_BackpressureBroker())

    async def backpressure() -> None:
        stream = _sse_stream(channel, ticket, heartbeat_seconds=1)
        with pytest.raises(StopAsyncIteration):
            await anext(stream)

    asyncio.run(backpressure())

    configure_broker(InMemoryRealtimeBroker())
    configure_realtime(principal_validator=lambda _p, _c: False)

    async def revoked_at_heartbeat() -> None:
        stream = _sse_stream(channel, ticket, heartbeat_seconds=0.001)
        with pytest.raises(StopAsyncIteration):
            await anext(stream)

    asyncio.run(revoked_at_heartbeat())

    configure_broker(_FiniteBroker())
    configure_realtime(principal_validator=lambda _p, _c: False)

    async def revoked_before_payload() -> None:
        stream = _sse_stream(channel, ticket, heartbeat_seconds=1)
        with pytest.raises(StopAsyncIteration):
            await anext(stream)

    asyncio.run(revoked_before_payload())


def test_websocket_inbound_close_paths_and_outbound_delivery() -> None:
    principal = _principal(EDITOR)
    ticket = ConnectionTicket(
        principal, "notes.live", "websocket", audience=str(principal.id)
    )
    async def exercise() -> None:
        too_large = _WebSocketDouble(["x" * (64 * 1024 + 1)])
        channel = RealtimeChannel(
            "notes.live",
            Notice,
            mode="websocket",
            inbound_model=Command,
            on_message=lambda _session, _principal, _message: None,
        )
        await _websocket_inbound(too_large, channel, ticket)
        assert too_large.closed == [(1009, "message too large")]

        configure_realtime(principal_validator=lambda _p, _c: False)
        revoked = _WebSocketDouble(['{"action":"refresh"}'])
        await _websocket_inbound(revoked, channel, ticket)
        assert revoked.closed == [(1008, "session no longer valid")]
        reset_realtime_configuration()

        push_only = RealtimeChannel("notes.push", Notice, mode="websocket")
        refused = _WebSocketDouble(['{"action":"refresh"}'])
        await _websocket_inbound(refused, push_only, ticket)
        assert refused.closed == [(1008, "channel is server-push only")]

        outbound_socket = _WebSocketDouble()
        configure_broker(_FiniteBroker())
        await _websocket_outbound(outbound_socket, channel, ticket)  # type: ignore[arg-type]
        assert outbound_socket.sent == ['{"sequence":3,"text":"pushed"}']

        configure_realtime(principal_validator=lambda _p, _c: False)
        revoked_outbound = _WebSocketDouble()
        await _websocket_outbound(revoked_outbound, channel, ticket)  # type: ignore[arg-type]
        assert revoked_outbound.sent == []
        assert revoked_outbound.closed == [(1008, "session no longer valid")]

        revoked_idle = _WebSocketDouble()
        await _websocket_liveness(
            revoked_idle, ticket, interval_seconds=0  # type: ignore[arg-type]
        )
        assert revoked_idle.closed == [(1008, "session no longer valid")]

    asyncio.run(exercise())


def test_websocket_awaits_async_handler_under_the_audit_actor() -> None:
    from terp.core.audit import current_actor_id

    principal = _principal(EDITOR)
    ticket = ConnectionTicket(
        principal, "notes.async", "websocket", audience=str(principal.id)
    )
    observed: list[uuid.UUID | None] = []

    async def on_message(
        _session: Session, _principal: Principal, _message: BaseModel
    ) -> None:
        observed.append(current_actor_id())
        await asyncio.sleep(0)
        observed.append(current_actor_id())

    channel = RealtimeChannel(
        "notes.async",
        Notice,
        mode="websocket",
        inbound_model=Command,
        on_message=on_message,
    )
    socket = _WebSocketDouble(['{"action":"refresh"}'])
    sessions: list[object] = []
    closed: list[object] = []

    def session_provider():
        session = object()
        sessions.append(session)
        try:
            yield session
        finally:
            closed.append(session)

    configure_realtime(message_session_provider=session_provider)  # type: ignore[arg-type]

    with pytest.raises(WebSocketDisconnect):
        asyncio.run(_websocket_inbound(socket, channel, ticket))
    assert observed == [principal.id, principal.id]
    assert len(sessions) == 1
    assert closed == sessions


def test_websocket_sync_handler_gets_a_fresh_closed_session_per_frame() -> None:
    principal = _principal(EDITOR)
    ticket = ConnectionTicket(
        principal, "notes.sync", "websocket", audience=str(principal.id)
    )
    sessions: list[object] = []
    closed: list[object] = []
    observed: list[object] = []

    def session_provider():
        session = object()
        sessions.append(session)
        try:
            yield session
        finally:
            closed.append(session)

    def on_message(session, _principal, _message) -> None:
        observed.append(session)

    configure_realtime(message_session_provider=session_provider)  # type: ignore[arg-type]
    channel = RealtimeChannel(
        "notes.sync",
        Notice,
        mode="websocket",
        inbound_model=Command,
        on_message=on_message,
    )
    socket = _WebSocketDouble(
        ['{"action":"first"}', '{"action":"second"}']
    )

    with pytest.raises(WebSocketDisconnect):
        asyncio.run(_websocket_inbound(socket, channel, ticket))

    assert len(sessions) == 2
    assert observed == sessions
    assert closed == sessions


def test_websocket_handler_session_contract_fails_closed() -> None:
    principal = _principal(EDITOR)
    ticket = ConnectionTicket(
        principal, "notes.contract", "websocket", audience=str(principal.id)
    )

    def empty_provider():
        if False:
            yield object()

    configure_realtime(message_session_provider=empty_provider)  # type: ignore[arg-type]
    channel = RealtimeChannel(
        "notes.contract",
        Notice,
        mode="websocket",
        inbound_model=Command,
        on_message=lambda _session, _principal, _message: None,
    )
    with pytest.raises(RuntimeError, match="yielded no session"):
        asyncio.run(
            _websocket_inbound(
                _WebSocketDouble(['{"action":"refresh"}']), channel, ticket
            )
        )

    def session_provider():
        yield object()

    async def work() -> None:
        await asyncio.sleep(0)

    def misdeclared_handler(_session, _principal, _message):
        return work()

    configure_realtime(message_session_provider=session_provider)  # type: ignore[arg-type]
    misdeclared = RealtimeChannel(
        "notes.misdeclared",
        Notice,
        mode="websocket",
        inbound_model=Command,
        on_message=misdeclared_handler,
    )
    with pytest.raises(TypeError, match="declare it with async def"):
        asyncio.run(
            _websocket_inbound(
                _WebSocketDouble(['{"action":"refresh"}']),
                misdeclared,
                ConnectionTicket(
                    principal,
                    misdeclared.name,
                    "websocket",
                    audience=str(principal.id),
                ),
            )
        )


def test_websocket_supports_an_async_callable_handler() -> None:
    principal = _principal(EDITOR)
    observed: list[uuid.UUID] = []

    def session_provider():
        yield object()

    class AsyncHandler:
        async def __call__(self, _session, actor: Principal, _message) -> None:
            await asyncio.sleep(0)
            observed.append(actor.id)

    configure_realtime(message_session_provider=session_provider)  # type: ignore[arg-type]
    channel = RealtimeChannel(
        "notes.callable",
        Notice,
        mode="websocket",
        inbound_model=Command,
        on_message=AsyncHandler(),
    )
    ticket = ConnectionTicket(
        principal, channel.name, "websocket", audience=str(principal.id)
    )

    with pytest.raises(WebSocketDisconnect):
        asyncio.run(
            _websocket_inbound(
                _WebSocketDouble(['{"action":"refresh"}']), channel, ticket
            )
        )
    assert observed == [principal.id]


def test_websocket_async_handler_contract_fails_closed() -> None:
    principal = _principal(EDITOR)

    def session_provider():
        yield object()

    class BrokenAsyncHandler:
        def __call__(self, _session, _principal, _message) -> None:
            return None

    handler = BrokenAsyncHandler()

    async def async_marker(_session, _principal, _message) -> None:
        return None

    handler.__call__ = async_marker  # type: ignore[method-assign]
    configure_realtime(message_session_provider=session_provider)  # type: ignore[arg-type]
    channel = RealtimeChannel(
        "notes.broken-async",
        Notice,
        mode="websocket",
        inbound_model=Command,
        on_message=handler,
    )
    ticket = ConnectionTicket(
        principal, channel.name, "websocket", audience=str(principal.id)
    )

    with pytest.raises(TypeError, match="returned a non-awaitable"):
        asyncio.run(
            _websocket_inbound(
                _WebSocketDouble(['{"action":"refresh"}']), channel, ticket
            )
        )


def test_invalid_websocket_ticket_closes_before_accept() -> None:
    socket = _WebSocketDouble()

    async def exercise() -> None:
        await subscribe_websocket(
            socket,  # type: ignore[arg-type]
            "missing",
            "missing-ticket",
            object(),  # type: ignore[arg-type]
        )

    asyncio.run(exercise())
    assert socket.accepted is False
    assert socket.closed == [(1008, "invalid connection ticket")]


def test_websocket_task_results_ignore_expected_and_raise_unexpected() -> None:
    _raise_unexpected_task_results(
        [None, WebSocketDisconnect(1000), BackpressureError(), asyncio.CancelledError()]
    )
    with pytest.raises(RuntimeError, match="boom"):
        _raise_unexpected_task_results([RuntimeError("boom")])


def test_sse_rejects_a_ticket_that_fails_live_validation() -> None:
    channel = register_channel(RealtimeChannel("notes.revoked", Notice))
    principal = _principal(VIEWER)
    token = get_ticket_store().issue(
        ConnectionTicket(
            principal,
            channel.name,
            "sse",
            credential="dead",
            audience=str(principal.id),
        ),
        ttl_seconds=30,
    )
    configure_realtime(principal_validator=lambda _principal, _credential: False)
    from terp.core import AuthenticationError

    with pytest.raises(AuthenticationError):
        subscribe_sse(channel.name, token)


def _app(principal: Principal):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)

    def session_override() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app = create_app([module], discover_capabilities=False)
    app.dependency_overrides[get_principal] = lambda: principal
    app.dependency_overrides[get_session] = session_override
    configure_realtime(message_session_provider=session_override)
    return app


def test_sse_ticket_endpoint_is_authenticated_and_single_use() -> None:
    channel = register_channel(RealtimeChannel("notes.changed", Notice))
    principal = _principal(EDITOR)
    with TestClient(_app(principal)) as client:
        minted = client.post(
            "/api/v1/realtime/tickets",
            json={"channel": channel.name, "transport": "sse"},
        )
        assert minted.status_code == 201, minted.text
        ticket = minted.json()["ticket"]
        # A real SSE response intentionally stays open, so exercise the route
        # boundary directly: first redemption returns the stream response;
        # replay is rejected before streaming begins.
        response = subscribe_sse(channel.name, ticket)
        assert response.media_type == "text/event-stream"
        from terp.core import AuthenticationError

        with pytest.raises(AuthenticationError):
            subscribe_sse(channel.name, ticket)


def test_websocket_bidirectional_round_trip_and_ticket_replay_refusal() -> None:
    received: list[tuple[uuid.UUID, str, uuid.UUID | None]] = []

    def on_message(_session: Session, principal: Principal, message: BaseModel) -> None:
        from terp.core.audit import current_actor_id

        assert isinstance(message, Command)
        # An audited write inside the handler must know who acted: the route
        # binds the ticket principal exactly like the HTTP audit-actor binder.
        received.append((principal.id, message.action, current_actor_id()))

    channel = register_channel(
        RealtimeChannel(
            "notes.live",
            Notice,
            mode="websocket",
            inbound_model=Command,
            on_message=on_message,
        )
    )
    principal = _principal(EDITOR)
    with TestClient(_app(principal)) as client:
        minted = client.post(
            "/api/v1/realtime/tickets",
            json={"channel": channel.name, "transport": "websocket"},
        )
        assert minted.status_code == 201, minted.text
        ticket = minted.json()["ticket"]
        with client.websocket_connect(
            f"/api/v1/realtime/ws/{channel.name}?ticket={ticket}"
        ) as websocket:
            websocket.send_text('{"action":"refresh"}')
            # Invalid messages are typed errors, not handler calls/crashes.
            websocket.send_text('{"wrong":true}')
            assert websocket.receive_json() == {
                "type": "error",
                "code": "invalid_message",
            }
        assert received == [(principal.id, "refresh", principal.id)]

        with pytest.raises(Exception):
            with client.websocket_connect(
                f"/api/v1/realtime/ws/{channel.name}?ticket={ticket}"
            ):
                pass


def test_websocket_teardown_preserves_the_hosts_cancellation() -> None:
    """Cancelling the connection task mid-drain must surface the HOST's own
    CancelledError. anyio's cancel scopes (the ASGI server, starlette's test
    portal) absorb only a cancellation carrying their own scope message; a
    gather-based drain re-raised the last child's untagged copy instead,
    crashing every teardown that raced the drain."""

    async def scenario() -> str | None:
        in_drain = asyncio.Event()
        release = asyncio.Event()

        async def stubborn() -> None:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                in_drain.set()
                with contextlib.suppress(asyncio.CancelledError):
                    await release.wait()
                raise

        first = asyncio.create_task(asyncio.sleep(0))
        hanging = asyncio.create_task(stubborn())
        settle = asyncio.create_task(_settle_websocket_tasks(first, hanging))
        await in_drain.wait()
        # The exact shape of an anyio host-task cancellation (see
        # anyio._backends._asyncio.is_anyio_cancellation).
        settle.cancel("Cancelled via cancel scope 0xterp")
        release.set()
        try:
            await settle
        except asyncio.CancelledError as exc:
            return str(exc.args[0]) if exc.args else None
        finally:
            hanging.cancel()
            await asyncio.wait({hanging})
        return "settle finished without raising the host's cancellation"

    message = asyncio.run(scenario())
    assert message is not None
    assert message.startswith("Cancelled via cancel scope")


def test_settle_websocket_tasks_drains_and_surfaces_unexpected_results() -> None:
    """The uncancelled settle path: cancelled tasks are tolerated silently,
    normal returns collected, and an unexpected exception still propagates."""

    async def scenario() -> None:
        async def hang() -> None:
            await asyncio.Event().wait()

        async def fine() -> None:
            return None

        await _settle_websocket_tasks(
            asyncio.create_task(fine()), asyncio.create_task(hang())
        )

        async def boom() -> None:
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            await _settle_websocket_tasks(
                asyncio.create_task(boom()), asyncio.create_task(hang())
            )

    asyncio.run(scenario())
