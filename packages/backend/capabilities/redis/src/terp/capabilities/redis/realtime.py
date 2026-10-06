"""Redis-backed realtime tickets and fan-out (the ``terp-cap-redis[realtime]`` extra).

The realtime capability's one-use connection tickets and its broker are per-process by
default. A deployment where a publish and its subscriber can sit in different processes
(several replicas, or a job handler in ``terp jobs worker``) shares both here: the
replica that serves the WebSocket upgrade can consume a ticket another replica issued,
and a message published anywhere reaches a subscriber everywhere (ADR 0176). This
submodule is the only place terp-cap-redis touches terp-cap-realtime: importing it
requires the ``realtime`` extra (``terp-cap-redis[realtime]``), so the shared kernel
stores in :mod:`terp.capabilities.redis.stores` never drag a self-registering transport
capability onto the path.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any

from terp.capabilities.realtime import (
    ConnectionTicket,
    ConnectionTicketStore,
    RealtimeBroker,
    SubscriptionEnded,
    mark_shared_broker,
)
from terp.core import Principal, Role

from terp.capabilities.redis.stores import (
    _async_client_from_url,
    _client_from_url,
    _redis,
    _text,
)

_CONSUME_TICKET_SCRIPT = """
local value = redis.call('GET', KEYS[1])
if not value then
    return nil
end
redis.call('DEL', KEYS[1])
return value
"""


class RedisConnectionTicketStore(ConnectionTicketStore):
    """Shared one-use realtime tickets with atomic GET+DEL consumption."""

    def __init__(self, client: Any, *, namespace: str = "terp") -> None:
        self._client = client
        self._prefix = f"{namespace}:realtime-ticket:"

    @classmethod
    def from_url(
        cls, url: str, *, namespace: str = "terp"
    ) -> RedisConnectionTicketStore:
        return cls(_client_from_url(url), namespace=namespace)

    def issue(self, ticket: ConnectionTicket, *, ttl_seconds: int) -> str:
        if ttl_seconds <= 0:
            raise ValueError(
                "RedisConnectionTicketStore.issue requires a positive ttl_seconds"
            )
        token = uuid.uuid4().hex + uuid.uuid4().hex
        value = json.dumps(
            {
                "principal_id": str(ticket.principal.id),
                "role_name": ticket.principal.role.name,
                "role_rank": ticket.principal.role.rank,
                "channel": ticket.channel,
                "transport": ticket.transport,
                "credential": ticket.credential,
                "audience": ticket.audience,
            },
            separators=(",", ":"),
        )
        self._client.set(self._key(token), value, ex=int(ttl_seconds))
        return token

    def consume(
        self, token: str, *, channel: str, transport: str
    ) -> ConnectionTicket | None:
        raw = self._client.eval(_CONSUME_TICKET_SCRIPT, 1, self._key(token))
        if raw is None:
            return None
        payload = json.loads(_text(raw))
        if payload["channel"] != channel or payload["transport"] != transport:
            return None
        return ConnectionTicket(
            principal=Principal(
                id=uuid.UUID(payload["principal_id"]),
                role=Role(payload["role_name"], int(payload["role_rank"])),
            ),
            channel=payload["channel"],
            transport=payload["transport"],
            credential=payload.get("credential", ""),
            audience=payload.get("audience", ""),
        )

    def _key(self, token: str) -> str:
        return f"{self._prefix}{token}"


class RedisRealtimeBroker(RealtimeBroker):
    """Realtime fan-out over Redis pub/sub, shared by every process on the same server.

    A publish goes to Redis, and every process holding a subscriber on that topic
    receives it, whichever process published: another replica, or a job handler in
    ``terp jobs worker``. The adapter marks itself shared, so
    ``configure_realtime(require_shared_broker=True)`` accepts it.

    Each subscriber holds its own pub/sub connection while its transport is open. That
    bounds a slow consumer as the in-process queue does: Redis buffers for a subscriber
    up to the server's ``client-output-buffer-limit pubsub``, then drops the connection,
    and the stream raises :class:`SubscriptionEnded`, so the transport closes and the
    browser reconnects. Delivery is fire-and-forget, as it is in process: a message
    published while nobody is subscribed reaches nobody.

    ``publish`` runs the synchronous client on a worker thread, so it works from any event
    loop, including one ``asyncio.run`` opened for a sync hook, without blocking it.
    ``stream`` opens an asyncio client inside the subscriber's own loop.
    """

    def __init__(
        self,
        client: Any,
        *,
        subscriber_factory: Callable[[], Any],
        namespace: str = "terp",
    ) -> None:
        self._client = client
        self._subscriber_factory = subscriber_factory
        self._prefix = f"{namespace}:realtime:"
        mark_shared_broker(self)

    @classmethod
    def from_url(cls, url: str, *, namespace: str = "terp") -> RedisRealtimeBroker:
        return cls(
            _client_from_url(url),
            subscriber_factory=lambda: _async_client_from_url(url),
            namespace=namespace,
        )

    async def publish(self, channel: str, payload: str) -> None:
        await asyncio.to_thread(self._client.publish, self._key(channel), payload)

    def stream(self, channel: str) -> AsyncIterator[str]:
        return self._subscription(self._key(channel))

    async def _subscription(self, key: str) -> AsyncIterator[str]:
        lost = _connection_errors()
        client = self._subscriber_factory()
        pubsub = client.pubsub(ignore_subscribe_messages=True)
        try:
            try:
                await pubsub.subscribe(key)
                async for message in pubsub.listen():
                    if message.get("type") == "message":
                        yield _text(message["data"])
            except lost as exc:
                raise SubscriptionEnded(
                    "realtime subscription lost its Redis connection; the client reconnects"
                ) from exc
        finally:
            await pubsub.aclose()
            await client.aclose()

    def _key(self, channel: str) -> str:
        return f"{self._prefix}{channel}"


def _connection_errors() -> tuple[type[BaseException], ...]:
    """The redis-py errors that mean the server or the link dropped a subscriber."""
    exceptions = _redis().exceptions
    return (exceptions.ConnectionError, exceptions.TimeoutError)


__all__ = ["RedisConnectionTicketStore", "RedisRealtimeBroker"]
