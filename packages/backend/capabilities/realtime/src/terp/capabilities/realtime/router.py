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
from collections.abc import AsyncIterator, Callable
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, ValidationError
from sqlmodel import Session
from starlette.responses import StreamingResponse

from terp.core import (
    AuthorizationRequirement,
    ModuleSpec,
    PermissionDeniedError,
    PermissionEnforcer,
    Policy,
    Principal,
    SessionDep,
    bind_audit_actor,
    get_principal,
)

from terp.capabilities.realtime.broker import (
    BackpressureError,
    audience_topic,
    get_broker,
)
from terp.capabilities.realtime.channel import RealtimeChannel, get_channel
from terp.capabilities.realtime.tickets import ConnectionTicket, get_ticket_store

TICKET_TTL_SECONDS = 30
HEARTBEAT_SECONDS = 15.0
MAX_INBOUND_BYTES = 64 * 1024

PrincipalValidator = Callable[[Principal, str], bool]

_permission_enforcer: PermissionEnforcer | None = None
_principal_validator: PrincipalValidator | None = None


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
) -> None:
    """Wire optional authorization/revocation seams at composition time.

    A channel whose requirement is a Permission denies fail-closed unless
    ``permission_enforcer`` is present. ``principal_validator`` may revalidate
    long-lived connections at handshake/heartbeat/frame boundaries; without it,
    authority is the live principal captured by the 30-second ticket mint.
    """
    global _permission_enforcer, _principal_validator
    _permission_enforcer = permission_enforcer
    _principal_validator = principal_validator


def reset_realtime_configuration() -> None:
    """Restore optional seam defaults (test isolation)."""
    configure_realtime()


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


def _bearer_credential(request: Request) -> str:
    header = request.headers.get("Authorization", "")
    if not header.lower().startswith("bearer "):
        return ""
    return header[7:].strip()


router = APIRouter(tags=["realtime"])


@router.post("/tickets", response_model=TicketResponse, status_code=201)
def mint_ticket(
    payload: TicketRequest,
    request: Request,
    session: SessionDep,
    principal: Principal | None = Depends(get_principal),
) -> TicketResponse:
    if principal is None:
        # Defensive: the module guard already rejects this endpoint, but the
        # handler remains fail-closed when called directly in tests.
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


def _sse_data(payload: str) -> bytes:
    # The broker accepts only Pydantic-produced compact JSON; replace CR/LF as
    # defense in depth so one payload can never inject an SSE field/event.
    safe = payload.replace("\r", "").replace("\n", "")
    return f"data: {safe}\n\n".encode("utf-8")


async def _sse_stream(
    channel: RealtimeChannel,
    audience: str,
    *,
    heartbeat_seconds: float = HEARTBEAT_SECONDS,
) -> AsyncIterator[bytes]:
    iterator = get_broker().stream(
        audience_topic(channel.name, audience)
    ).__aiter__()
    pending = asyncio.create_task(anext(iterator))
    try:
        while True:
            done, _ = await asyncio.wait(
                {pending}, timeout=heartbeat_seconds
            )
            if not done:
                yield b": keepalive\n\n"
                continue
            try:
                payload = pending.result()
            except (StopAsyncIteration, BackpressureError):
                return
            yield _sse_data(payload)
            pending = asyncio.create_task(anext(iterator))
    finally:
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
        await iterator.aclose()


@router.get(
    "/sse/{channel_name}",
    response_model=None,
    response_class=StreamingResponse,
)
def subscribe_sse(
    channel_name: str,
    ticket: Annotated[str, Query(min_length=1, max_length=200)],
) -> StreamingResponse:
    channel = get_channel(channel_name)
    redeemed = _consume_ticket(ticket, channel_name=channel_name, transport="sse")
    if channel is None or channel.mode != "sse" or redeemed is None:
        from terp.core import AuthenticationError

        raise AuthenticationError()
    if not _validate_live(redeemed):
        from terp.core import AuthenticationError

        raise AuthenticationError()
    return StreamingResponse(
        _sse_stream(channel, redeemed.audience),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store",
            "X-Accel-Buffering": "no",
        },
    )


async def _websocket_outbound(
    websocket: WebSocket, channel: RealtimeChannel, audience: str
) -> None:
    async for payload in get_broker().stream(
        audience_topic(channel.name, audience)
    ):
        await websocket.send_text(payload)


async def _websocket_inbound(
    websocket: WebSocket,
    channel: RealtimeChannel,
    ticket: ConnectionTicket,
    session: Session,
) -> None:
    while True:
        text = await websocket.receive_text()
        if len(text.encode("utf-8")) > MAX_INBOUND_BYTES:
            await websocket.close(code=1009, reason="message too large")
            return
        if not _validate_live(ticket):
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
        # The HTTP guard's audit-actor binder never saw this connection (the
        # handshake authenticated by ticket), so an audited write inside the
        # handler must still know WHO acted: bind the ticket's principal for
        # exactly the handler call, mirroring what the binder does per request.
        with bind_audit_actor(ticket.principal.id):
            channel.on_message(session, ticket.principal, message)


def _raise_unexpected_task_results(results: list[object]) -> None:
    for result in results:
        if isinstance(result, BaseException) and not isinstance(
            result,
            (WebSocketDisconnect, BackpressureError, asyncio.CancelledError),
        ):
            raise result


@router.websocket("/ws/{channel_name}")
async def subscribe_websocket(
    websocket: WebSocket,
    channel_name: str,
    ticket: Annotated[str, Query(min_length=1, max_length=200)],
    session: SessionDep,
) -> None:
    channel = get_channel(channel_name)
    redeemed = _consume_ticket(
        ticket, channel_name=channel_name, transport="websocket"
    )
    if (
        channel is None
        or channel.mode != "websocket"
        or redeemed is None
        or not _validate_live(redeemed)
    ):
        await websocket.close(code=1008, reason="invalid connection ticket")
        return
    await websocket.accept()
    outbound = asyncio.create_task(
        _websocket_outbound(websocket, channel, redeemed.audience)
    )
    inbound = asyncio.create_task(
        _websocket_inbound(websocket, channel, redeemed, session)
    )
    done, pending = await asyncio.wait(
        {outbound, inbound}, return_when=asyncio.FIRST_COMPLETED
    )
    for task in pending:
        task.cancel()
    results = await asyncio.gather(*done, *pending, return_exceptions=True)
    _raise_unexpected_task_results(results)


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
    "TICKET_TTL_SECONDS",
    "PrincipalValidator",
    "TicketRequest",
    "TicketResponse",
    "configure_realtime",
    "module",
    "reset_realtime_configuration",
    "router",
]
