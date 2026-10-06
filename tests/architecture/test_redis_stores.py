"""Redis store adapters: shared idempotency, throttling, cache, and extra-gated stores.

The suite drives the adapters over a tiny in-repo Redis double instead of a live server, but
keeps the adapter's public surface intact: the idempotency and throttle paths still go
through the Lua-script ``eval`` calls, cache values go through Redis string commands, and the
shared-store boot markers are asserted through the public kernel predicates.
"""

from __future__ import annotations

import asyncio
import datetime
import importlib
import logging
import pathlib
import tomllib
import uuid
from collections.abc import Callable, Iterable
from typing import Any

import pytest

# RedisConnectionTicketStore / RedisOIDCStateStore resolve through the package root's
# lazy __getattr__ (they live behind the [realtime] / [oidc] extras) — importing them
# here exercises that hook.
from terp.capabilities.redis import (
    RedisCacheStore,
    RedisConnectionTicketStore,
    RedisIdempotencyStore,
    RedisOIDCStateStore,
    RedisRealtimeBroker,
    RedisStoreBundle,
    RedisThrottleStore,
)
from terp.capabilities.oidc import OIDCStateStore
from terp.capabilities.realtime import (
    ConnectionTicket,
    InMemoryRealtimeBroker,
    SubscriptionEnded,
    configure_broker,
    configure_realtime,
    get_broker,
    is_shared_broker,
    reset_realtime_configuration,
)
from terp.capabilities.redis import realtime as redis_realtime
from terp.capabilities.redis import stores as redis_stores
from terp.core import (
    EDITOR,
    Principal,
    StoredResponse,
    is_shared_cache_store,
    is_shared_idempotency_store,
    is_shared_throttle_store,
)

_RESPONSE = StoredResponse(status_code=201, headers=(("content-type", "application/json"),), body=b"{}")
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


class _FakeRedis:
    """A minimal Redis command double for the commands this adapter uses."""

    def __init__(self, *, bytes_mode: bool = True) -> None:
        self.now = 0
        self.bytes_mode = bytes_mode
        self._values: dict[str, tuple[object, int | None]] = {}

    def eval(self, script: str, numkeys: int, *args: object) -> list[object]:
        assert numkeys == 1
        key = str(args[0])
        self._expire_key(key)
        if "'fingerprint', ARGV[1]" in script:
            return self._begin(key, str(args[1]), str(args[2]), int(args[3]))
        if "'status', ARGV[2]" in script:
            return self._complete(key, str(args[1]), str(args[2]), str(args[3]), args[4], int(args[5]))
        if "return redis.call('DEL', KEYS[1])" in script:
            return [self.delete(key)] if self._hget(key, "lease") == str(args[1]) else [0]
        if "local count = redis.call('INCR'" in script:
            return self._hit(key, int(args[1]))
        if "local value = redis.call('GET'" in script:
            value = self.get(key)
            self.delete(key)
            return value  # type: ignore[return-value]
        raise AssertionError(f"unexpected script: {script}")

    def get(self, key: str) -> object | None:
        self._expire_key(key)
        entry = self._values.get(key)
        if entry is None:
            return None
        value, _expires_at = entry
        return self._out(value)

    def set(self, key: str, value: object, *, ex: int) -> None:
        self._values[key] = (value, self.now + ex)

    def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            self._expire_key(key)
            if key in self._values:
                removed += 1
                del self._values[key]
        return removed

    def ttl(self, key: str) -> int:
        self._expire_key(key)
        entry = self._values.get(key)
        if entry is None:
            return -2
        _value, expires_at = entry
        if expires_at is None:
            return -1
        return max(0, expires_at - self.now)

    def _begin(self, key: str, fingerprint: str, lease: str, ttl: int) -> list[object]:
        entry = self._hash(key)
        if entry is None:
            self._values[key] = ({"fingerprint": fingerprint, "lease": lease, "done": "0"}, self.now + ttl)
            return [self._out("started"), self._out(lease)]
        if entry["fingerprint"] != fingerprint:
            return [self._out("mismatch")]
        if entry["done"] != "1":
            return [self._out("in_flight")]
        return [
            self._out("replay"),
            self._out(entry["status"]),
            self._out(entry["headers"]),
            self._out(entry["body"]),
        ]

    def _complete(
        self, key: str, lease: str, status: str, headers: str, body: object, ttl: int
    ) -> list[object]:
        entry = self._hash(key)
        if entry is None or entry.get("lease") != lease:
            return [0]
        if not self.bytes_mode and isinstance(body, bytes):
            body = body.decode("utf-8")
        entry.update({"done": "1", "status": status, "headers": headers, "body": body})
        self._values[key] = (entry, self.now + ttl)
        return [1]

    def _hit(self, key: str, window: int) -> list[int]:
        count = int(self.get(key) or 0) + 1
        if count == 1:
            self._values[key] = (str(count), self.now + window)
        else:
            _value, expires_at = self._values[key]
            self._values[key] = (str(count), expires_at)
        ttl = self.ttl(key)
        if ttl < 0:
            ttl = window
            self._values[key] = (str(count), self.now + window)
        return [count, ttl]

    def _hash(self, key: str) -> dict[str, object] | None:
        entry = self._values.get(key)
        if entry is None:
            return None
        value, _expires_at = entry
        assert isinstance(value, dict)
        return value

    def _hget(self, key: str, field: str) -> object | None:
        entry = self._hash(key)
        return None if entry is None else entry.get(field)

    def _expire_key(self, key: str) -> None:
        entry = self._values.get(key)
        if entry is not None and entry[1] is not None and entry[1] <= self.now:
            del self._values[key]

    def _out(self, value: object) -> object:
        if self.bytes_mode and isinstance(value, str):
            return value.encode("utf-8")
        return value


@pytest.mark.parametrize("factory", [RedisStoreBundle.from_client])
def test_bundle_marks_all_three_stores_as_shared(factory: object) -> None:
    bundle = factory(_FakeRedis(), namespace="test")
    assert is_shared_idempotency_store(bundle.idempotency) is True
    assert is_shared_throttle_store(bundle.throttle) is True
    assert is_shared_cache_store(bundle.cache) is True
    assert isinstance(bundle.realtime_tickets, RedisConnectionTicketStore)


def test_from_url_constructors_create_clients_without_connecting() -> None:
    assert RedisIdempotencyStore.from_url("redis://localhost/0")
    assert RedisThrottleStore.from_url("redis://localhost/0")
    assert RedisCacheStore.from_url("redis://localhost/0")
    assert RedisConnectionTicketStore.from_url("redis://localhost/0")
    assert RedisRealtimeBroker.from_url("redis://localhost/0")
    assert redis_realtime._subscriber_from_url("redis://localhost/0")
    assert RedisStoreBundle.from_url("redis://localhost/0")


def test_redis_idempotency_begin_complete_replay_lifecycle() -> None:
    store = RedisIdempotencyStore(_FakeRedis())
    first = store.begin("k", "fp", ttl_seconds=60)
    assert first.state == "started"
    assert first.lease is not None
    assert store.begin("k", "fp", ttl_seconds=60).state == "in_flight"
    assert store.begin("k", "other-fp", ttl_seconds=60).state == "mismatch"

    store.complete("k", first.lease, _RESPONSE, ttl_seconds=60)
    replay = store.begin("k", "fp", ttl_seconds=60)
    assert replay.state == "replay"
    assert replay.response == _RESPONSE
    assert store.begin("k", "other-fp", ttl_seconds=60).state == "mismatch"


def test_redis_idempotency_release_and_stale_lease_are_guarded() -> None:
    client = _FakeRedis()
    store = RedisIdempotencyStore(client)
    first = store.begin("k", "fp", ttl_seconds=10)
    assert first.lease is not None
    store.release("k", "stale")
    store.complete("k", "stale", _RESPONSE, ttl_seconds=60)
    assert store.begin("k", "fp", ttl_seconds=10).state == "in_flight"

    client.now = 10
    second = store.begin("k", "fp", ttl_seconds=10)
    assert second.state == "started"
    assert second.lease is not None
    store.complete("k", first.lease, _RESPONSE, ttl_seconds=60)
    assert store.begin("k", "fp", ttl_seconds=10).state == "in_flight"
    store.release("k", second.lease)
    assert store.begin("k", "fp", ttl_seconds=10).state == "started"


def test_redis_idempotency_validates_ttls() -> None:
    store = RedisIdempotencyStore(_FakeRedis())
    with pytest.raises(ValueError, match="positive ttl_seconds"):
        store.begin("k", "fp", ttl_seconds=0)
    with pytest.raises(ValueError, match="positive ttl_seconds"):
        store.complete("k", "lease", _RESPONSE, ttl_seconds=-1)


def test_redis_idempotency_handles_string_responses_from_decoded_clients() -> None:
    store = RedisIdempotencyStore(_FakeRedis(bytes_mode=False))
    first = store.begin("k", "fp", ttl_seconds=60)
    assert first.lease is not None
    store.complete("k", first.lease, _RESPONSE, ttl_seconds=60)
    assert store.begin("k", "fp", ttl_seconds=60).response == _RESPONSE


def test_redis_throttle_fixed_window_lock_and_clear() -> None:
    client = _FakeRedis()
    store = RedisThrottleStore(client)
    assert store.hit("k", 60) == (1, 60)
    client.now = 10
    assert store.hit("k", 60) == (2, 50)
    client.now = 60
    assert store.hit("k", 60) == (1, 60)

    store.lock("k", 30)
    assert store.locked("k") == 30
    client.now = 61
    assert store.locked("k") == 29
    store.clear("k")
    assert store.locked("k") == 0
    assert store.hit("k", 60)[0] == 1


def test_redis_cache_get_set_delete_and_ttl_validation() -> None:
    client = _FakeRedis(bytes_mode=False)
    store = RedisCacheStore(client)
    assert store.get("k") is None
    store.set("k", "v", ttl_seconds=10)
    assert store.get("k") == "v"
    client.now = 10
    assert store.get("k") is None
    store.set("k", "v2", ttl_seconds=10)
    store.delete("k")
    assert store.get("k") is None
    with pytest.raises(ValueError, match="positive ttl_seconds"):
        store.set("k", "v", ttl_seconds=0)


def test_redis_realtime_ticket_is_atomic_single_use_exact_match_and_ttl_bounded() -> None:
    client = _FakeRedis(bytes_mode=False)
    store = RedisConnectionTicketStore(client)
    ticket = ConnectionTicket(
        Principal(id=uuid.uuid4(), role=EDITOR),
        "notes.live",
        "websocket",
        credential="access-token",
        audience="tenant-a",
    )
    token = store.issue(ticket, ttl_seconds=10)
    assert store.consume(token, channel="notes.live", transport="websocket") == ticket
    assert store.consume(token, channel="notes.live", transport="websocket") is None

    token = store.issue(ticket, ttl_seconds=10)
    assert store.consume(token, channel="other", transport="websocket") is None
    assert store.consume(token, channel="notes.live", transport="websocket") is None

    token = store.issue(ticket, ttl_seconds=10)
    client.now = 10
    assert store.consume(token, channel="notes.live", transport="websocket") is None
    with pytest.raises(ValueError, match="positive"):
        store.issue(ticket, ttl_seconds=0)


class _FakePubSubServer:
    """One Redis server's pub/sub, shared by every client a test builds over it.

    ``publish`` arrives on a worker thread (the broker runs the synchronous client
    through ``asyncio.to_thread``), so delivery crosses into each subscriber's loop
    the way a socket read would. ``confirms`` and ``answers_pings`` switch the server's
    replies off, for one that took a command and then went silent.
    """

    def __init__(self) -> None:
        self.channels: dict[str, list[_FakePubSub]] = {}
        self.published: list[tuple[str, str]] = []
        self.confirms = True
        self.answers_pings = True

    def publish(self, key: str, payload: str) -> int:
        self.published.append((key, payload))
        subscribers = list(self.channels.get(key, ()))
        for pubsub in subscribers:
            pubsub.deliver({"type": "message", "channel": key.encode(), "data": payload.encode()})
        return len(subscribers)


class _FakePubSub:
    """redis-py's asyncio ``PubSub`` as the broker uses it: ``get_message`` waits at most
    ``timeout`` seconds and returns ``None`` when nothing came, and the SUBSCRIBE and
    PING replies arrive as messages of their own."""

    def __init__(
        self, server: _FakePubSubServer, *, unreachable: BaseException | None = None
    ) -> None:
        self.server = server
        self.unreachable = unreachable
        self.keys: list[str] = []
        self.pings = 0
        self.reads = 0
        self.ping_error: BaseException | None = None
        self.close_error: BaseException | None = None
        self.closed = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._inbox: asyncio.Queue[object] | None = None

    async def subscribe(self, key: str) -> None:
        if self.unreachable is not None:
            raise self.unreachable
        self._loop = asyncio.get_running_loop()
        self._inbox = asyncio.Queue()
        self.keys.append(key)
        self.server.channels.setdefault(key, []).append(self)
        if self.server.confirms:
            self.deliver({"type": "subscribe", "channel": key.encode(), "data": 1})

    def deliver(self, item: object) -> None:
        assert self._loop is not None and self._inbox is not None
        self._loop.call_soon_threadsafe(self._inbox.put_nowait, item)

    async def get_message(self, *, timeout: float) -> object | None:
        assert self._inbox is not None
        self.reads += 1
        try:
            item = await asyncio.wait_for(self._inbox.get(), timeout)
        except TimeoutError:
            return None
        if isinstance(item, BaseException):
            raise item
        return item

    async def ping(self) -> None:
        self.pings += 1
        if self.ping_error is not None:
            raise self.ping_error
        if self.server.answers_pings:
            self.deliver({"type": "pong", "pattern": None, "channel": None, "data": b""})

    async def aclose(self) -> None:
        self.closed = True
        for key in self.keys:
            self.server.channels[key].remove(self)
        if self.close_error is not None:
            raise self.close_error


class _FakeSubscriberClient:
    def __init__(
        self, server: _FakePubSubServer, *, unreachable: BaseException | None = None
    ) -> None:
        self.server = server
        self.unreachable = unreachable
        self.pubsubs: list[_FakePubSub] = []
        self.closed = False

    def pubsub(self) -> _FakePubSub:
        pubsub = _FakePubSub(self.server, unreachable=self.unreachable)
        self.pubsubs.append(pubsub)
        return pubsub

    async def aclose(self) -> None:
        self.closed = True


def _broker_over(
    server: _FakePubSubServer,
    *,
    unreachable: BaseException | None = None,
    idle_seconds: float = 30.0,
) -> tuple[RedisRealtimeBroker, list[_FakeSubscriberClient]]:
    """A broker over *server*, with the subscriber clients it opens kept for inspection."""
    clients: list[_FakeSubscriberClient] = []

    def subscriber() -> _FakeSubscriberClient:
        clients.append(_FakeSubscriberClient(server, unreachable=unreachable))
        return clients[-1]

    broker = RedisRealtimeBroker(
        server, subscriber_factory=subscriber, idle_seconds=idle_seconds
    )
    return broker, clients


async def _until(condition: Callable[[], bool]) -> None:
    async with asyncio.timeout(5):
        while not condition():
            await asyncio.sleep(0)


async def _subscribed(server: _FakePubSubServer, key: str) -> _FakePubSub:
    await _until(lambda: bool(server.channels.get(key)))
    return server.channels[key][-1]


_KEY = "terp:0:realtime:notes\x00user-a"


def test_redis_realtime_broker_carries_a_publish_from_one_process_to_another() -> None:
    # Two brokers over one server stand for two processes: a web replica holding the
    # browser's subscription, and a job worker that serves no transport and publishes.
    server = _FakePubSubServer()
    web_clients: list[_FakeSubscriberClient] = []

    def web_subscriber() -> _FakeSubscriberClient:
        client = _FakeSubscriberClient(server)
        web_clients.append(client)
        return client

    web = RedisRealtimeBroker(server, subscriber_factory=web_subscriber, namespace="t")
    worker = RedisRealtimeBroker(server, subscriber_factory=lambda: None, namespace="t")
    assert is_shared_broker(web) and is_shared_broker(worker)
    key = "t:0:realtime:notes\x00user-a"

    async def exercise() -> None:
        # stream() subscribes at its first read, as the in-process broker's does.
        stream = web.stream("notes\x00user-a").__aiter__()
        pending = asyncio.create_task(anext(stream))
        pubsub = await _subscribed(server, key)
        pubsub.deliver({"type": "pong", "data": b""})  # not a message: never yielded
        await worker.publish("notes\x00user-b", "another audience")
        await worker.publish("notes\x00user-a", '{"sequence":1}')
        assert await pending == '{"sequence":1}'
        await stream.aclose()

    asyncio.run(exercise())
    assert server.published == [
        ("t:0:realtime:notes\x00user-b", "another audience"),
        (key, '{"sequence":1}'),
    ]
    (client,) = web_clients
    assert client.closed and client.pubsubs[0].closed
    assert server.channels[key] == []


def test_redis_realtime_broker_is_subscribed_when_subscribe_returns() -> None:
    # The transports subscribe before they answer the browser, so subscribe() returns
    # only once Redis confirmed the SUBSCRIBE: a publish straight after it is received.
    server = _FakePubSubServer()
    broker, clients = _broker_over(server)

    async def exercise() -> None:
        messages = await broker.subscribe("notes\x00user-a")
        assert [pubsub.keys for pubsub in server.channels[_KEY]] == [[_KEY]]
        await broker.publish("notes\x00user-a", "first")
        assert await anext(messages) == "first"
        await messages.aclose()

    asyncio.run(exercise())
    (client,) = clients
    assert client.closed and client.pubsubs[0].closed


def test_redis_realtime_broker_refuses_a_subscription_redis_cannot_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refused = redis_stores._redis().exceptions.ConnectionError("Connection refused")
    broker, clients = _broker_over(_FakePubSubServer(), unreachable=refused)
    with pytest.raises(SubscriptionEnded) as raised:
        asyncio.run(broker.subscribe("notes\x00user-a"))
    assert raised.value.__cause__ is refused
    assert clients[0].closed and clients[0].pubsubs[0].closed

    # A server that took the SUBSCRIBE and never confirmed it is refused as well.
    monkeypatch.setattr(redis_realtime, "_CONNECTION_TIMEOUT_SECONDS", 0.01)
    silent = _FakePubSubServer()
    silent.confirms = False
    broker, clients = _broker_over(silent)
    with pytest.raises(SubscriptionEnded, match="did not confirm"):
        asyncio.run(broker.subscribe("notes\x00user-a"))
    assert clients[0].closed and clients[0].pubsubs[0].closed
    assert silent.channels[_KEY] == []


def test_redis_realtime_broker_ends_a_subscription_its_connection_lost() -> None:
    server = _FakePubSubServer()
    broker, clients = _broker_over(server)
    lost = redis_stores._redis().exceptions.ConnectionError("Connection reset by peer")

    async def exercise() -> None:
        stream = broker.stream("notes\x00user-a").__aiter__()
        pending = asyncio.create_task(anext(stream))
        pubsub = await _subscribed(server, _KEY)
        # A pub/sub close that fails must neither skip the client's close nor replace
        # the error that ended the subscription.
        pubsub.close_error = RuntimeError("close failed")
        pubsub.deliver(lost)
        with pytest.raises(SubscriptionEnded) as raised:
            await pending
        assert raised.value.__cause__ is lost

    asyncio.run(exercise())
    assert clients[0].closed and clients[0].pubsubs[0].closed


def test_redis_realtime_broker_closes_its_connection_when_cancelled_mid_wait() -> None:
    server = _FakePubSubServer()
    broker, clients = _broker_over(server)

    async def exercise() -> None:
        messages = await broker.subscribe("notes\x00user-a")
        pending = asyncio.create_task(anext(messages))
        pubsub = server.channels[_KEY][-1]
        await _until(lambda: pubsub.reads == 2)  # the confirmation, then the wait
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending

    asyncio.run(exercise())
    (client,) = clients
    assert client.pubsubs[0].closed and client.closed


def test_redis_realtime_broker_pings_a_quiet_connection_and_gives_up_on_silence() -> None:
    # A subscriber dropped without a word (no reset ever arrives) would wait forever on a
    # quiet channel. Idle for idle_seconds, it pings; silent as long again, it ends.
    server = _FakePubSubServer()
    broker, _clients = _broker_over(server, idle_seconds=0.01)

    async def answered_then_silent() -> None:
        messages = await broker.subscribe("notes\x00user-a")
        pending = asyncio.create_task(anext(messages))
        pubsub = server.channels[_KEY][-1]
        await _until(lambda: pubsub.pings >= 2)  # each ping answered: still subscribed
        await broker.publish("notes\x00user-a", "still here")
        assert await pending == "still here"
        server.answers_pings = False
        with pytest.raises(SubscriptionEnded, match="did not answer"):
            await anext(messages)

    asyncio.run(answered_then_silent())

    reset = redis_stores._redis().exceptions.ConnectionError("Connection reset by peer")

    async def ping_fails() -> None:
        messages = await broker.subscribe("notes\x00user-a")
        server.channels[_KEY][-1].ping_error = reset
        with pytest.raises(SubscriptionEnded) as raised:
            await anext(messages)
        assert raised.value.__cause__ is reset

    asyncio.run(ping_fails())


def test_redis_realtime_broker_ends_a_subscription_redis_py_resubscribed() -> None:
    # redis-py may reconnect a dropped pub/sub connection and SUBSCRIBE again by itself.
    # What was published in the gap is gone, so the stream ends and the client re-reads.
    server = _FakePubSubServer()
    broker, clients = _broker_over(server)

    async def exercise() -> None:
        messages = await broker.subscribe("notes\x00user-a")
        server.channels[_KEY][-1].deliver({"type": "subscribe", "data": 1})
        with pytest.raises(SubscriptionEnded, match="reconnected"):
            await anext(messages)

    asyncio.run(exercise())
    assert clients[0].closed


def test_redis_realtime_broker_rejects_a_non_positive_idle_interval() -> None:
    with pytest.raises(ValueError, match="positive idle_seconds"):
        RedisRealtimeBroker(_FakePubSubServer(), subscriber_factory=lambda: None, idle_seconds=0)


class _PoolBoundClient:
    """A sync client that says which database it is bound to, as redis-py's does."""

    def __init__(self, server: _FakePubSubServer, connection_kwargs: dict[str, object]) -> None:
        self.server = server
        self.connection_pool = type("Pool", (), {"connection_kwargs": connection_kwargs})()

    def publish(self, key: str, payload: str) -> int:
        return self.server.publish(key, payload)


def test_redis_realtime_channels_carry_the_database_index() -> None:
    # Pub/sub is server-wide: two deployments on one server, on databases 0 and 1, must
    # not hear each other under the same namespace.
    server = _FakePubSubServer()
    on_db_1 = RedisRealtimeBroker(
        _PoolBoundClient(server, {"db": 1}), subscriber_factory=lambda: None
    )
    unsaid = RedisRealtimeBroker(
        _PoolBoundClient(server, {"host": "localhost"}), subscriber_factory=lambda: None
    )
    asyncio.run(on_db_1.publish("notes\x00user-a", "one"))
    asyncio.run(unsaid.publish("notes\x00user-a", "zero"))
    assert server.published == [
        ("terp:1:realtime:notes\x00user-a", "one"),
        ("terp:0:realtime:notes\x00user-a", "zero"),
    ]
    assert RedisRealtimeBroker.from_url("redis://localhost/1")._key("c") == "terp:1:realtime:c"
    assert RedisRealtimeBroker.from_url("redis://localhost")._key("c") == "terp:0:realtime:c"


class _UnreachablePublisher:
    def __init__(self, error: BaseException) -> None:
        self.error = error

    def publish(self, key: str, payload: str) -> int:
        raise self.error


def test_redis_realtime_publish_never_fails_the_write_that_published(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # A publish rides a write path (an _after_write hook would roll the write back), so
    # a Redis that is down or does not answer drops the message and logs, without the
    # payload.
    errors = redis_stores._redis().exceptions
    with caplog.at_level(logging.WARNING, logger="terp.capabilities.redis.realtime"):
        for error in (errors.ConnectionError("refused"), errors.TimeoutError("timed out")):
            broker = RedisRealtimeBroker(
                _UnreachablePublisher(error), subscriber_factory=lambda: None
            )
            assert asyncio.run(broker.publish("notes\x00user-a", '{"secret":"x"}')) is None
    logged = [
        record.getMessage()
        for record in caplog.records
        if record.name == "terp.capabilities.redis.realtime"
    ]
    assert len(logged) == 2
    assert all("dropped" in line and "terp:0:realtime:" in line for line in logged)
    assert not any("secret" in line for line in logged)

    # A command Redis refused is not an outage: it still surfaces.
    refused = RedisRealtimeBroker(
        _UnreachablePublisher(errors.ResponseError("WRONGTYPE")),
        subscriber_factory=lambda: None,
    )
    with pytest.raises(errors.ResponseError):
        asyncio.run(refused.publish("notes\x00user-a", "{}"))


def test_redis_realtime_broker_bounds_its_own_clients_and_not_the_stores() -> None:
    broker = RedisRealtimeBroker.from_url("redis://localhost/0")
    publisher = broker._client.connection_pool.connection_kwargs
    subscriber = broker._subscriber_factory().connection_pool.connection_kwargs
    for options in (publisher, subscriber):
        assert options["socket_connect_timeout"] == 2.0
        assert options["socket_timeout"] == 2.0
    store = RedisCacheStore.from_url("redis://localhost/0")
    assert "socket_timeout" not in store._client.connection_pool.connection_kwargs


def test_redis_realtime_broker_satisfies_a_promised_shared_broker() -> None:
    try:
        configure_realtime(require_shared_broker=True)
        broker = RedisRealtimeBroker(_FakePubSubServer(), subscriber_factory=lambda: None)
        configure_broker(broker)
        assert get_broker() is broker
    finally:
        configure_broker(None)
        reset_realtime_configuration()
    assert isinstance(get_broker(), InMemoryRealtimeBroker)
    configure_broker(None)


def test_redis_oidc_state_is_shared_single_use_provider_matched_and_ttl_bounded() -> None:
    client = _FakeRedis(bytes_mode=False)
    store = RedisOIDCStateStore(client)
    assert isinstance(store, OIDCStateStore)

    state, pending = store.issue("corp")
    assert pending.provider == "corp"
    # Another replica (a second adapter over the same Redis) finishes the flow.
    other_replica = RedisOIDCStateStore(client)
    assert other_replica.consume(state, "corp") == pending
    assert store.consume(state, "corp") is None  # strictly single-use

    state, _ = store.issue("corp")
    assert store.consume(state, "other") is None  # cross-provider splice refused
    assert store.consume(state, "corp") is None  # ...and the state is spent

    short = RedisOIDCStateStore(client, ttl=datetime.timedelta(seconds=5))
    state, _ = short.issue("corp")
    client.now = 5
    assert short.consume(state, "corp") is None  # expired server-side (Redis TTL)

    assert RedisOIDCStateStore.from_url("redis://localhost/0")
    with pytest.raises(ValueError, match="positive ttl"):
        RedisOIDCStateStore(client, ttl=datetime.timedelta(seconds=0))


def test_redis_oidc_state_refuses_a_stale_payload_defensively() -> None:
    # The Redis TTL normally expires the key first; a payload that outlives it (e.g. a
    # clock skewed backwards) is still refused by the recorded expires_at.
    client = _FakeRedis(bytes_mode=False)
    store = RedisOIDCStateStore(client)
    state, pending = store.issue("corp")
    raw = client.get(f"terp:oidc-state:{state}")
    assert raw is not None
    stale = str(raw).replace(
        pending.expires_at.isoformat(),
        (pending.expires_at - datetime.timedelta(minutes=30)).isoformat(),
    )
    client.set(f"terp:oidc-state:{state}", stale, ex=600)
    assert store.consume(state, "corp") is None


def test_package_root_lazily_resolves_extra_exports_and_refuses_unknown_names() -> None:
    import terp.capabilities.redis as redis_pkg

    assert redis_pkg.RedisConnectionTicketStore is RedisConnectionTicketStore
    assert redis_pkg.RedisRealtimeBroker is RedisRealtimeBroker
    assert redis_pkg.RedisOIDCStateStore is RedisOIDCStateStore
    with pytest.raises(AttributeError, match="Nope"):
        _ = redis_pkg.Nope


def test_optional_exports_give_directive_errors_when_extra_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import terp.capabilities.redis as redis_pkg

    real_import_module = importlib.import_module

    def _missing_optional(name: str, package: str | None = None) -> Any:
        if name == "terp.capabilities.redis.realtime":
            raise ModuleNotFoundError(
                "No module named 'terp.capabilities.realtime'",
                name="terp.capabilities.realtime",
            )
        return real_import_module(name, package)

    monkeypatch.setattr(importlib, "import_module", _missing_optional)
    with pytest.raises(ModuleNotFoundError, match=r"terp-cap-redis\[realtime\]"):
        _ = redis_pkg.RedisConnectionTicketStore
    with pytest.raises(ModuleNotFoundError, match=r"terp-cap-redis\[realtime\]"):
        _ = redis_stores.RedisConnectionTicketStore
    bundle = RedisStoreBundle.from_client(_FakeRedis())
    assert bundle.realtime_tickets is None


def test_optional_exports_do_not_mask_broken_installed_adapters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import terp.capabilities.redis as redis_pkg

    real_import_module = importlib.import_module

    def _broken_adapter(name: str, package: str | None = None) -> Any:
        if name == "terp.capabilities.redis.realtime":
            raise ModuleNotFoundError("No module named 'adapter_dependency'", name="adapter_dependency")
        return real_import_module(name, package)

    monkeypatch.setattr(importlib, "import_module", _broken_adapter)
    with pytest.raises(ModuleNotFoundError, match="adapter_dependency"):
        _ = redis_pkg.RedisConnectionTicketStore
    with pytest.raises(ModuleNotFoundError, match="adapter_dependency"):
        _ = redis_stores.RedisConnectionTicketStore
    with pytest.raises(ModuleNotFoundError, match="adapter_dependency"):
        RedisStoreBundle.from_client(_FakeRedis())


def test_redis_adapter_extras_are_selective_and_composable() -> None:
    project = tomllib.loads(
        (
            _REPO_ROOT
            / "packages"
            / "backend"
            / "capabilities"
            / "redis"
            / "pyproject.toml"
        ).read_text(encoding="utf-8")
    )["project"]
    extras = project["optional-dependencies"]
    # Lockstep pins move every release; derive them so this test keeps asserting
    # the extras' shape rather than the version of the day.
    version = project["version"]
    realtime = f"terp-cap-realtime=={version}"
    oidc = f"terp-cap-oidc=={version}"
    assert extras["realtime"] == [realtime]
    assert extras["oidc"] == [oidc]
    assert set(extras["all"]) == {realtime, oidc}
    assert realtime not in project["dependencies"]
    assert oidc not in project["dependencies"]


def test_public_module_exports_are_complete() -> None:
    exported: Iterable[str] = redis_stores.__all__
    assert set(exported) == {
        "RedisCacheStore",
        "RedisIdempotencyStore",
        "RedisStoreBundle",
        "RedisThrottleStore",
    }
    import terp.capabilities.redis as redis_pkg
    from terp.capabilities.redis import oidc as redis_oidc
    from terp.capabilities.redis import realtime as redis_realtime

    assert set(redis_pkg.__all__) == set(exported)
    assert redis_stores.RedisConnectionTicketStore is RedisConnectionTicketStore
    assert redis_realtime.__all__ == ["RedisConnectionTicketStore", "RedisRealtimeBroker"]
    assert redis_oidc.__all__ == ["RedisOIDCStateStore"]
