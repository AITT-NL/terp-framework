"""Authenticated ticket mint + SSE/WebSocket transport endpoints.

The HTTP mint endpoint runs behind the capability's normal deny-by-default
``Policy`` and receives the live principal from the app's configured auth seam.
It applies the channel's typed authority requirement, then captures that
principal in a 30-second, single-use ticket. Browser-native transports redeem
the opaque ticket at handshake; the bearer token never enters a URL.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import contextmanager
from inspect import isawaitable, iscoroutinefunction
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, WebSocket
from pydantic import BaseModel, Field, ValidationError
from sqlmodel import Session
from starlette.responses import StreamingResponse

from terp.core import (
    AuthorizationRequirement,
    ModuleSpec,
    PermissionDeniedError,
    PermissionEnforcer,
    Policy,
    Roles,
    Principal,
    SessionDep,
    bind_audit_actor,
    get_principal,
    get_session,
    operation,
    route_policy,
)

from terp.capabilities.realtime.broker import (
    SubscriptionEnded,
    require_shared_broker as _require_shared_broker,
)
from terp.capabilities.realtime.channel import RealtimeChannel, get_channel
from terp.capabilities.realtime.operations import (
    REALTIME_MINT_TICKET,
    REALTIME_SUBSCRIBE_SSE,
    REALTIME_SUBSCRIBE_WEBSOCKET,
)
from terp.capabilities.realtime.tickets import ConnectionTicket, get_ticket_store
from terp.capabilities.realtime.transport import (
    RealtimeUnavailableError,
    _settle_websocket_tasks,
    _sse_data,
    open_subscription,
)

TICKET_TTL_SECONDS = 30
HEARTBEAT_SECONDS = 15.0
MAX_INBOUND_BYTES = 64 * 1024

PrincipalValidator = Callable[[Principal, str], bool]
MessageSessionProvider = Callable[[], Iterator[Session]]

_permission_enforcer: PermissionEnforcer | None = None
_principal_validator: PrincipalValidator | None = None
_message_session_provider: MessageSessionProvider | None = None


class TicketRequest(BaseModel):
    channel: str = Field(min_length=1, max_length=200)
    transport: Literal["sse", "websocket"]


class TicketResponse(BaseModel):
    ticket: str = Field(min_length=1, max_length=200)
    expires_in: int = Field(gt=0)
    channel: str = Field(min_length=1, max_length=200)
    transport: Literal["sse", "websocket"]


def configure_realtime(
    *,
    permission_enforcer: PermissionEnforcer | None = None,
    principal_validator: PrincipalValidator | None = None,
    message_session_provider: MessageSessionProvider | None = None,
    require_shared_broker: bool | None = None,
) -> None:
    """Wire optional authorization/revocation seams at composition time.

    A channel whose requirement is a Permission denies fail-closed unless
    ``permission_enforcer`` is present. ``principal_validator`` may revalidate
    long-lived connections at handshake/heartbeat/frame boundaries; without it,
    authority is the live principal captured by the 30-second ticket mint.
    ``message_session_provider`` supplies one fresh session per inbound frame;
    the core request-session provider is the default. ``require_shared_broker=True``
    promises a broker shared across processes and refuses a per-process one (ADR 0176);
    ``None`` leaves the promise as it stands, so a later call for the other seams keeps it.
    """
    global _permission_enforcer, _principal_validator, _message_session_provider
    if require_shared_broker is not None:
        _require_shared_broker(require_shared_broker)
    _permission_enforcer = permission_enforcer
    _principal_validator = principal_validator
    _message_session_provider = message_session_provider


def reset_realtime_configuration() -> None:
    """Restore optional seam defaults and withdraw the shared-broker promise (tests)."""
    configure_realtime(require_shared_broker=False)


def _authorize_requirement(
    requirement: AuthorizationRequirement,
    principal: Principal,
    session: Session,
) -> None:
    if principal.role.rank < requirement.min_rank:
        raise PermissionDeniedError()
    if requirement.kind == "permission" and (
        _permission_enforcer is None
        or not _permission_enforcer(session, principal.id, requirement.name)
    ):
        raise PermissionDeniedError()


def _authorize(channel: RealtimeChannel, principal: Principal, session: Session) -> None:
    _authorize_requirement(channel.requirement, principal, session)
    if channel.inbound_model is not None:
        _authorize_requirement(channel.inbound_requirement, principal, session)


def _validate_live(ticket: ConnectionTicket) -> bool:
    return _principal_validator is None or _principal_validator(
        ticket.principal, ticket.credential
    )


async def _validate_live_async(ticket: ConnectionTicket) -> bool:
    validator = _principal_validator
    if validator is None:
        return True
    return await asyncio.to_thread(
        validator, ticket.principal, ticket.credential
    )


@contextmanager
def _message_session() -> Iterator[Session]:
    sessions = (_message_session_provider or get_session)()
    try:
        session = next(sessions)
    except StopIteration as exc:
        raise RuntimeError("realtime message session provider yielded no session") from exc
    try:
        yield session
    finally:
        close = getattr(sessions, "close", None)
        if close is not None:
            close()


def _handler_is_async(handler: Callable[..., object]) -> bool:
    return iscoroutinefunction(handler) or iscoroutinefunction(
        getattr(handler, "__call__", None)
    )


def _run_sync_handler(
    handler: Callable[..., object],
    ticket: ConnectionTicket,
    message: BaseModel,
) -> None:
    with _message_session() as session, bind_audit_actor(ticket.principal.id):
        result = handler(session, ticket.principal, message)
        if isawaitable(result):
            close = getattr(result, "close", None)
            if close is not None:
                close()
            raise TypeError(
                "realtime sync handler returned an awaitable; declare it with async def"
            )


async def _run_inbound_handler(
    handler: Callable[..., object],
    ticket: ConnectionTicket,
    message: BaseModel,
) -> None:
    if not _handler_is_async(handler):
        await asyncio.to_thread(_run_sync_handler, handler, ticket, message)
        return
    with _message_session() as session, bind_audit_actor(ticket.principal.id):
        result = handler(session, ticket.principal, message)
        if not isawaitable(result):
            raise TypeError("realtime async handler returned a non-awaitable")
        await result


def _bearer_credential(request: Request) -> str:
    header = request.headers.get("Authorization", "")
    if not header.lower().startswith("bearer "):
        return ""
    return header[7:].strip()


router = APIRouter(tags=["realtime"])


@router.post("/tickets", response_model=TicketResponse, status_code=201)
# The mint endpoint is NOT part of the public handshake -- it is the authenticated
# step that issues the credential the handshake redeems. It was public only because
# its module is, and its own `principal is None` check was the only thing standing
# in front of it (ADR 0148).
#
# VIEWER on the write tier, not the EDITOR a bare `Policy.default()` would impose:
# minting a ticket is a POST that subscribes, not one that changes anything, and the
# authority that actually decides is the channel's own `_authorize` below. Defaulting
# here would have refused every VIEWER a realtime channel, which is most of the people
# a realtime channel exists for.
@route_policy(Policy(read=Roles.VIEWER, write=Roles.VIEWER))
@operation(REALTIME_MINT_TICKET)
def mint_ticket(
    payload: TicketRequest,
    request: Request,
    session: SessionDep,
    principal: Principal | None = Depends(get_principal),
) -> TicketResponse:
    if principal is None:
        # Defensive, and now true: this route declares `Policy.default()`, so the
        # module guard really does reject an anonymous caller before the handler
        # runs. The check stays because the handler is also called directly in
        # tests, where no guard is mounted.
        from terp.core import AuthenticationError

        raise AuthenticationError()
    channel = get_channel(payload.channel)
    if channel is None or channel.mode != payload.transport:
        # Do not reveal whether a guessed channel exists under another mode.
        raise PermissionDeniedError()
    _authorize(channel, principal, session)
    connection_ticket = ConnectionTicket(
            principal=principal,
            channel=channel.name,
            transport=payload.transport,
            credential=_bearer_credential(request),
            audience=channel.audience(session, principal),
        )
    if not _validate_live(connection_ticket):
        from terp.core import AuthenticationError

        raise AuthenticationError()
    ticket = get_ticket_store().issue(
        connection_ticket,
        ttl_seconds=TICKET_TTL_SECONDS,
    )
    return TicketResponse(
        ticket=ticket,
        expires_in=TICKET_TTL_SECONDS,
        channel=channel.name,
        transport=payload.transport,
    )


def _consume_ticket(
    token: str, *, channel_name: str, transport: str
) -> ConnectionTicket | None:
    return get_ticket_store().consume(
        token, channel=channel_name, transport=transport
    )


async def _sse_stream(
    messages: AsyncIterator[str],
    ticket: ConnectionTicket,
    *,
    heartbeat_seconds: float = HEARTBEAT_SECONDS,
) -> AsyncIterator[bytes]:
    pending = asyncio.create_task(anext(messages))
    try:
        while True:
            done, _ = await asyncio.wait(
                {pending}, timeout=heartbeat_seconds
            )
            if not done:
                if not await _validate_live_async(ticket):
                    return
                yield b": keepalive\n\n"
                continue
            try:
                payload = pending.result()
            except (StopAsyncIteration, SubscriptionEnded):
                return
            if not await _validate_live_async(ticket):
                return
            yield _sse_data(payload)
            pending = asyncio.create_task(anext(messages))
    finally:
        pending.cancel()
        # asyncio.wait, never gather — see transport._settle_websocket_tasks.
        await asyncio.wait({pending})
        await messages.aclose()


@router.get(
    "/sse/{channel_name}",
    response_model=None,
    response_class=StreamingResponse,
)
@route_policy(
    Policy.public(
        reason="an EventSource constructor cannot attach a bearer; the one-use "
        "ticket in the query is the credential"
    )
)
@operation(REALTIME_SUBSCRIBE_SSE)
async def subscribe_sse(
    channel_name: str,
    ticket: Annotated[str, Query(min_length=1, max_length=200)],
) -> StreamingResponse:
    channel = get_channel(channel_name)
    redeemed = await asyncio.to_thread(
        _consume_ticket, ticket, channel_name=channel_name, transport="sse"
    )
    if (
        channel is None
        or channel.mode != "sse"
        or redeemed is None
        or not await _validate_live_async(redeemed)
    ):
        from terp.core import AuthenticationError

        raise AuthenticationError()
    # Subscribe before answering: the 200 tells the browser it is subscribed, so a
    # subscription that cannot start is a 503 here, never a stream that ends at once.
    messages = await open_subscription(channel.name, redeemed.audience)
    return StreamingResponse(
        _sse_stream(messages, redeemed),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store",
            "X-Accel-Buffering": "no",
        },
    )


async def _websocket_outbound(
    websocket: WebSocket, messages: AsyncIterator[str], ticket: ConnectionTicket
) -> None:
    async for payload in messages:
        if not await _validate_live_async(ticket):
            await websocket.close(code=1008, reason="session no longer valid")
            return
        await websocket.send_text(payload)


async def _websocket_liveness(
    websocket: WebSocket,
    ticket: ConnectionTicket,
    *,
    interval_seconds: float = HEARTBEAT_SECONDS,
) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        if not await _validate_live_async(ticket):
            await websocket.close(code=1008, reason="session no longer valid")
            return


async def _websocket_inbound(
    websocket: WebSocket,
    channel: RealtimeChannel,
    ticket: ConnectionTicket,
) -> None:
    while True:
        text = await websocket.receive_text()
        if len(text.encode("utf-8")) > MAX_INBOUND_BYTES:
            await websocket.close(code=1009, reason="message too large")
            return
        if not await _validate_live_async(ticket):
            await websocket.close(code=1008, reason="session no longer valid")
            return
        if channel.inbound_model is None or channel.on_message is None:
            await websocket.close(code=1008, reason="channel is server-push only")
            return
        try:
            message = channel.inbound_model.model_validate_json(text)
        except ValidationError:
            await websocket.send_text(
                json.dumps(
                    {"type": "error", "code": "invalid_message"}, separators=(",", ":")
                )
            )
            continue
        await _run_inbound_handler(channel.on_message, ticket, message)


@router.websocket("/ws/{channel_name}")
@route_policy(
    Policy.public_write(
        reason="a WebSocket constructor cannot attach a bearer; the one-use ticket "
        "in the query is the credential, and a socket has no method to read as a "
        "safe one"
    )
)
@operation(REALTIME_SUBSCRIBE_WEBSOCKET)
async def subscribe_websocket(
    websocket: WebSocket,
    channel_name: str,
    ticket: Annotated[str, Query(min_length=1, max_length=200)],
    handshake_session: SessionDep,
) -> None:
    channel = get_channel(channel_name)
    redeemed = _consume_ticket(
        ticket, channel_name=channel_name, transport="websocket"
    )
    if (
        channel is None
        or channel.mode != "websocket"
        or redeemed is None
        or not await _validate_live_async(redeemed)
    ):
        await websocket.close(code=1008, reason="invalid connection ticket")
        return
    # Global guard/audit dependencies resolve one request session even for this
    # ticket-authenticated public route. Release it before the long-lived socket;
    # each inbound frame gets a fresh, bounded message unit of work instead.
    handshake_session.close()
    # Subscribe before accepting: an accepted socket tells the browser it is subscribed.
    try:
        messages = await open_subscription(channel.name, redeemed.audience)
    except RealtimeUnavailableError:
        await websocket.close(code=1013, reason="realtime unavailable; try again later")
        return
    await websocket.accept()
    outbound = asyncio.create_task(
        _websocket_outbound(websocket, messages, redeemed)
    )
    inbound = asyncio.create_task(
        _websocket_inbound(websocket, channel, redeemed)
    )
    liveness = asyncio.create_task(_websocket_liveness(websocket, redeemed))
    await _settle_websocket_tasks(outbound, inbound, liveness)


module = ModuleSpec(
    name="realtime",
    router=router,
    # Native EventSource/WebSocket constructors cannot attach the in-memory
    # bearer header, so the transport handshake is public at the HTTP layer
    # and authenticates by a 30-second, single-use ticket instead. The mint
    # endpoint self-authenticates with Depends(get_principal), then enforces
    # the channel's typed authority. The stronger public-write declaration
    # makes this exceptional route posture explicit and runtime-validated.
    policy=Policy.public_write(
        reason="realtime handshakes redeem one-use authenticated connection tickets"
    ),
)


__all__ = [
    "HEARTBEAT_SECONDS",
    "MAX_INBOUND_BYTES",
    "MessageSessionProvider",
    "TICKET_TTL_SECONDS",
    "PrincipalValidator",
    "TicketRequest",
    "TicketResponse",
    "configure_realtime",
    "module",
    "reset_realtime_configuration",
    "router",
]
