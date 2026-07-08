"""Redis store adapters: shared idempotency, throttling, and cache semantics.

The suite drives the adapters over a tiny in-repo Redis double instead of a live server, but
keeps the adapter's public surface intact: the idempotency and throttle paths still go
through the Lua-script ``eval`` calls, cache values go through Redis string commands, and the
shared-store boot markers are asserted through the public kernel predicates.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import pytest

from terp.capabilities.redis import (
    RedisCacheStore,
    RedisIdempotencyStore,
    RedisStoreBundle,
    RedisThrottleStore,
)
from terp.capabilities.redis import stores as redis_stores
from terp.core import (
    StoredResponse,
    is_shared_cache_store,
    is_shared_idempotency_store,
    is_shared_throttle_store,
)

_RESPONSE = StoredResponse(status_code=201, headers=(("content-type", "application/json"),), body=b"{}")


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


def test_from_url_constructors_create_clients_without_connecting() -> None:
    assert RedisIdempotencyStore.from_url("redis://localhost/0")
    assert RedisThrottleStore.from_url("redis://localhost/0")
    assert RedisCacheStore.from_url("redis://localhost/0")
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


def test_public_module_exports_are_complete() -> None:
    exported: Iterable[str] = redis_stores.__all__
    assert set(exported) == {
        "RedisCacheStore",
        "RedisIdempotencyStore",
        "RedisStoreBundle",
        "RedisThrottleStore",
    }
