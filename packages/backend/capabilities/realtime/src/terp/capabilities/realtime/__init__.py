"""terp.capabilities.realtime — sanctioned typed SSE + WebSocket channels.

App modules never touch raw transports. They declare a :class:`RealtimeChannel`,
register it, and publish Pydantic messages through :func:`publish`; the
self-registering capability exposes the authenticated ticket + transport
router. Browser code subscribes through ``@terp/react-core``'s
``useRealtimeChannel`` hook, which mints its one-use ticket with the generated
client before opening EventSource/WebSocket.
"""

from __future__ import annotations

from pydantic import BaseModel

from terp.capabilities.realtime.broker import (
    BackpressureError,
    InMemoryRealtimeBroker,
    RealtimeBroker,
    audience_topic,
    configure_broker,
    get_broker,
)
from terp.capabilities.realtime.channel import (
    AudienceResolver,
    InboundHandler,
    RealtimeAuthzRef,
    RealtimeChannel,
    clear_channels,
    global_audience,
    get_channel,
    register_channel,
    registered_channels,
    principal_audience,
)
from terp.capabilities.realtime.router import (
    HEARTBEAT_SECONDS,
    MAX_INBOUND_BYTES,
    TICKET_TTL_SECONDS,
    PrincipalValidator,
    configure_realtime,
    module,
    reset_realtime_configuration,
    router,
)
from terp.capabilities.realtime.tickets import (
    ConnectionTicket,
    ConnectionTicketStore,
    InMemoryConnectionTicketStore,
    configure_ticket_store,
    get_ticket_store,
)


async def publish(
    channel: RealtimeChannel, message: BaseModel, *, audience: str
) -> None:
    """Validate and publish *message* to one explicit channel *audience*."""
    if get_channel(channel.name) != channel:
        raise ValueError(
            f"realtime channel {channel.name!r} is not registered with this declaration"
        )
    validated = channel.outbound_model.model_validate(message)
    await get_broker().publish(
        audience_topic(channel.name, audience), validated.model_dump_json()
    )


__all__ = [
    "AudienceResolver",
    "BackpressureError",
    "ConnectionTicket",
    "ConnectionTicketStore",
    "HEARTBEAT_SECONDS",
    "InboundHandler",
    "InMemoryConnectionTicketStore",
    "InMemoryRealtimeBroker",
    "MAX_INBOUND_BYTES",
    "PrincipalValidator",
    "RealtimeBroker",
    "RealtimeChannel",
    "RealtimeAuthzRef",
    "TICKET_TTL_SECONDS",
    "clear_channels",
    "audience_topic",
    "configure_broker",
    "configure_realtime",
    "configure_ticket_store",
    "get_broker",
    "get_channel",
    "get_ticket_store",
    "global_audience",
    "module",
    "publish",
    "principal_audience",
    "register_channel",
    "registered_channels",
    "reset_realtime_configuration",
    "router",
]
