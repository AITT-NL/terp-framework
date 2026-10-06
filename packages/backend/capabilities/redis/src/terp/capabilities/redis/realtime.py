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
import logging
import uuid
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from contextlib import AsyncExitStack
from typing import Any, cast

from terp.capabilities.realtime import (
    ConnectionTicket,
    ConnectionTicketStore,
    RealtimeBroker,
    SubscriptionEnded,
    mark_shared_broker,
)
from terp.core import Principal, Role

from terp.capabilities.redis.stores import _client_from_url, _redis, _text

#: How long a subscriber's connection may stay silent before the broker pings Redis.
#: Silence for as long again after the ping ends the subscription as lost, so a
#: connection that died without a word (no reset ever arrived) cannot hang forever.
_SUBSCRIBER_IDLE_SECONDS = 30.0

#: The bound on connecting to Redis and on each command's reply, for the publisher and
#: for every subscriber, so neither a publish on a request's write path nor a transport
#: waiting on its subscription is held up for long by a Redis that does not answer.
_CONNECTION_TIMEOUT_SECONDS = 2.0

_logger = logging.getLogger("terp.capabilities.redis.realtime")

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

    Pub/sub is server-wide: a channel belongs to the server, not to one of its numbered
    databases. The channel names therefore carry the publishing client's database index
    beside the namespace, so deployments that share a server on different databases do
    not hear each other. Deployments that share a server *and* a database must use
    distinct namespaces.

    Each subscriber holds its own pub/sub connection while its transport is open, and
    :meth:`subscribe` connects and has Redis confirm the SUBSCRIBE before it returns, so
    a transport refuses the browser when Redis is unreachable rather than answering and
    ending at once. A slow consumer is bounded as the in-process queue bounds it: Redis
    buffers for a subscriber up to the server's ``client-output-buffer-limit pubsub``,
    then drops the connection. A connection silent for ``idle_seconds`` is pinged, and
    one still silent as long again is given up. A dropped connection, an unanswered ping
    and a reconnect redis-py made by itself (the messages of the gap are gone) all end
    the stream with :class:`SubscriptionEnded`, so the transport closes and the browser
    reconnects.

    Delivery is fire-and-forget, as it is in process: a message published while nobody is
    subscribed reaches nobody, and a publish Redis does not take is dropped with a
    warning in the log instead of failing the write that published it. ``from_url``
    bounds connecting and each reply at two seconds (and its clients do not retry), so a
    Redis that does not answer holds a publish up for seconds, not minutes. ``publish``
    runs the synchronous client on a worker thread, so it works from any event loop,
    including one ``asyncio.run`` opened for a sync hook, without blocking it. A
    subscriber's asyncio client opens in its own loop.
    """

    def __init__(
        self,
        client: Any,
        *,
        subscriber_factory: Callable[[], Any],
        namespace: str = "terp",
        idle_seconds: float = _SUBSCRIBER_IDLE_SECONDS,
    ) -> None:
        if idle_seconds <= 0:
            raise ValueError("RedisRealtimeBroker requires a positive idle_seconds")
        self._client = client
        self._subscriber_factory = subscriber_factory
        self._idle_seconds = idle_seconds
        self._prefix = f"{namespace}:{_database_index(client)}:realtime:"
        mark_shared_broker(self)

    @classmethod
    def from_url(cls, url: str, *, namespace: str = "terp") -> RedisRealtimeBroker:
        return cls(
            _publisher_from_url(url),
            subscriber_factory=lambda: _subscriber_from_url(url),
            namespace=namespace,
        )

    async def publish(self, channel: str, payload: str) -> None:
        try:
            await asyncio.to_thread(self._client.publish, self._key(channel), payload)
        except _connection_errors() as exc:
            # Fire-and-forget: a publish rides a write path (an _after_write hook, a job
            # handler), and an unreachable Redis must not fail the write it reports.
            _logger.warning(
                "realtime publish dropped: Redis did not take it (%s) [prefix=%s]",
                type(exc).__name__,
                self._prefix,
            )

    def stream(self, channel: str) -> AsyncIterator[str]:
        subscription = self._subscription(self._key(channel), announce=False)
        return cast("AsyncIterator[str]", subscription)

    async def subscribe(self, channel: str) -> AsyncIterator[str]:
        subscription = self._subscription(self._key(channel), announce=True)
        await anext(subscription)  # returns once Redis confirmed the SUBSCRIBE
        return cast("AsyncIterator[str]", subscription)

    async def _subscription(
        self, key: str, *, announce: bool
    ) -> AsyncGenerator[str | None, None]:
        lost = _connection_errors()
        async with AsyncExitStack() as connection:
            client = self._subscriber_factory()
            connection.push_async_callback(_close_quietly, client)
            pubsub = client.pubsub()
            connection.push_async_callback(_close_quietly, pubsub)
            try:
                await pubsub.subscribe(key)
                reply = await pubsub.get_message(timeout=_CONNECTION_TIMEOUT_SECONDS)
                if reply is None or reply.get("type") != "subscribe":
                    raise SubscriptionEnded("Redis did not confirm the realtime subscription")
                if announce:
                    yield None  # subscribed: subscribe() hands the stream to its caller
                pinged = False
                while True:
                    message = await pubsub.get_message(timeout=self._idle_seconds)
                    if message is None:
                        if pinged:
                            raise SubscriptionEnded("Redis did not answer the subscriber's ping")
                        await pubsub.ping()
                        pinged = True
                        continue
                    pinged = False
                    if message.get("type") == "message":
                        yield _text(message["data"])
                    elif message.get("type") == "subscribe":
                        raise SubscriptionEnded(
                            "redis-py reconnected the subscriber; what was published "
                            "meanwhile is gone, so the client reconnects and re-reads"
                        )
            except lost as exc:
                raise SubscriptionEnded(
                    "realtime subscription lost its Redis connection; the client reconnects"
                ) from exc

    def _key(self, channel: str) -> str:
        return f"{self._prefix}{channel}"


def _database_index(client: Any) -> int:
    """The numbered database *client* is bound to, or 0 when the client does not say."""
    try:
        return int(client.connection_pool.connection_kwargs.get("db", 0))
    except (AttributeError, TypeError, ValueError):
        return 0


def _publisher_from_url(url: str) -> Any:
    """The broker's synchronous publish client, with connecting and each reply bounded.

    The stores' client keeps redis-py's defaults; a publish rides a write path, so this
    one gives up on a Redis that does not answer within the bound.
    """
    return _redis().Redis.from_url(
        url,
        socket_connect_timeout=_CONNECTION_TIMEOUT_SECONDS,
        socket_timeout=_CONNECTION_TIMEOUT_SECONDS,
    )


def _subscriber_from_url(url: str) -> Any:
    """One subscriber's asyncio client, bounded the same way; it belongs to its loop.

    The bound covers connecting and each command. Waiting for messages is paced by the
    subscription itself (``get_message`` with the idle interval), so it is not cut short.
    """
    return _redis().asyncio.Redis.from_url(
        url,
        socket_connect_timeout=_CONNECTION_TIMEOUT_SECONDS,
        socket_timeout=_CONNECTION_TIMEOUT_SECONDS,
    )


async def _close_quietly(resource: Any) -> None:
    """Close one half of a subscriber's connection, whatever happened to the other.

    A failed close must neither skip closing the client after its pub/sub nor replace
    the error that ended the subscription, so it is logged at debug level and dropped.
    """
    try:
        await resource.aclose()
    except Exception:
        _logger.debug("closing a realtime subscriber's Redis connection failed", exc_info=True)


def _connection_errors() -> tuple[type[BaseException], ...]:
    """The redis-py errors that mean the server or the link dropped a client."""
    exceptions = _redis().exceptions
    return (exceptions.ConnectionError, exceptions.TimeoutError)


__all__ = ["RedisConnectionTicketStore", "RedisRealtimeBroker"]
