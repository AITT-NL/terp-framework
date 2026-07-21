"""Redis implementations of Terp's kernel store ports (idempotency, throttle, cache).

The three ports have deliberately narrow contracts, so the adapter keeps Redis usage narrow
as well: one namespaced key per logical entry, explicit TTLs on every value, and Lua only
where a multi-command transition must be indivisible. That gives horizontally scaled Terp
apps honest global behaviour without teaching the kernel about Redis or weakening the
single-process defaults.
"""

from __future__ import annotations

import base64
import json
import uuid
from dataclasses import dataclass
from typing import Any

from terp.core import (
    BeginOutcome,
    CacheStore,
    IdempotencyStore,
    StoredResponse,
    ThrottleStore,
    mark_shared_cache_store,
    mark_shared_idempotency_store,
    mark_shared_throttle_store,
)

_BEGIN_SCRIPT = """
local fingerprint = redis.call('HGET', KEYS[1], 'fingerprint')
if not fingerprint then
  redis.call('HSET', KEYS[1], 'fingerprint', ARGV[1], 'lease', ARGV[2], 'done', '0')
  redis.call('EXPIRE', KEYS[1], tonumber(ARGV[3]))
  return {'started', ARGV[2]}
end
if fingerprint ~= ARGV[1] then
  return {'mismatch'}
end
if redis.call('HGET', KEYS[1], 'done') ~= '1' then
  return {'in_flight'}
end
return {
  'replay',
  redis.call('HGET', KEYS[1], 'status'),
  redis.call('HGET', KEYS[1], 'headers'),
  redis.call('HGET', KEYS[1], 'body')
}
"""

_COMPLETE_SCRIPT = """
if redis.call('HGET', KEYS[1], 'lease') ~= ARGV[1] then
  return 0
end
redis.call(
  'HSET', KEYS[1],
  'done', '1',
  'status', ARGV[2],
  'headers', ARGV[3],
  'body', ARGV[4]
)
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[5]))
return 1
"""

_RELEASE_SCRIPT = """
if redis.call('HGET', KEYS[1], 'lease') == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""

_HIT_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
  redis.call('EXPIRE', KEYS[1], tonumber(ARGV[1]))
end
local ttl = redis.call('TTL', KEYS[1])
if ttl < 0 then
  redis.call('EXPIRE', KEYS[1], tonumber(ARGV[1]))
  ttl = tonumber(ARGV[1])
end
return {count, ttl}
"""

def _client_from_url(url: str) -> Any:
    """Construct a redis-py client lazily so importing the adapter stays lightweight."""
    from redis import Redis  # arch-allow-no-adhoc-background-runtime: this capability IS the Redis adapter for shared store seams — the one governed place the engine is imported

    return Redis.from_url(url)


def _text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


def _bytes(value: object) -> bytes:
    if isinstance(value, bytes):
        return value
    return str(value).encode("utf-8")


class RedisIdempotencyStore(IdempotencyStore):
    """A Redis-backed :class:`~terp.core.IdempotencyStore` with atomic claims.

    ``begin`` is a single Lua transition: the first caller creates an in-flight hash with a
    random lease and TTL; concurrent callers see ``in_flight``; completed hashes replay only
    when the fingerprint matches; reuse under a different fingerprint is always a
    ``mismatch``. ``complete`` and ``release`` are also Lua lease checks, so a slow request
    whose claim expired cannot overwrite or delete a newer claim.
    """

    def __init__(self, client: Any, *, namespace: str = "terp") -> None:
        self._client = client
        self._prefix = f"{namespace}:idempotency:"
        mark_shared_idempotency_store(self)

    @classmethod
    def from_url(cls, url: str, *, namespace: str = "terp") -> RedisIdempotencyStore:
        """Create the store from a Redis URL using redis-py's ``Redis.from_url``."""
        return cls(_client_from_url(url), namespace=namespace)

    def begin(self, key: str, fingerprint: str, *, ttl_seconds: int) -> BeginOutcome:
        if ttl_seconds <= 0:
            raise ValueError(
                f"RedisIdempotencyStore.begin requires a positive ttl_seconds, got {ttl_seconds!r}"
            )
        lease = uuid.uuid4().hex
        result = self._client.eval(
            _BEGIN_SCRIPT,
            1,
            self._key(key),
            fingerprint,
            lease,
            int(ttl_seconds),
        )
        parts = list(result)
        state = _text(parts[0])
        if state == "started":
            return BeginOutcome(state="started", lease=_text(parts[1]))
        if state == "in_flight":
            return BeginOutcome(state="in_flight")
        if state == "mismatch":
            return BeginOutcome(state="mismatch")
        headers = tuple((str(name), str(value)) for name, value in json.loads(_text(parts[2])))
        body = base64.b64decode(_bytes(parts[3]))
        response = StoredResponse(status_code=int(_text(parts[1])), headers=headers, body=body)
        return BeginOutcome(state="replay", response=response)

    def complete(
        self, key: str, lease: str, response: StoredResponse, *, ttl_seconds: int
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError(
                f"RedisIdempotencyStore.complete requires a positive ttl_seconds, got {ttl_seconds!r}"
            )
        headers = json.dumps(list(response.headers), separators=(",", ":"))
        self._client.eval(
            _COMPLETE_SCRIPT,
            1,
            self._key(key),
            lease,
            str(response.status_code),
            headers,
            base64.b64encode(response.body).decode("ascii"),
            int(ttl_seconds),
        )

    def release(self, key: str, lease: str) -> None:
        self._client.eval(_RELEASE_SCRIPT, 1, self._key(key), lease)

    def _key(self, key: str) -> str:
        return f"{self._prefix}{key}"


class RedisThrottleStore(ThrottleStore):
    """A Redis fixed-window counter and lockout store.

    Hit counters are namespaced strings whose first increment sets the window TTL in the
    same Lua script. Locks are separate TTL strings, so clearing a key removes both the
    counter and the lock while callers retain the port's simple ``hit`` / ``lock`` /
    ``locked`` contract.
    """

    def __init__(self, client: Any, *, namespace: str = "terp") -> None:
        self._client = client
        self._hits_prefix = f"{namespace}:throttle:h:"
        self._locks_prefix = f"{namespace}:throttle:l:"
        mark_shared_throttle_store(self)

    @classmethod
    def from_url(cls, url: str, *, namespace: str = "terp") -> RedisThrottleStore:
        """Create the store from a Redis URL using redis-py's ``Redis.from_url``."""
        return cls(_client_from_url(url), namespace=namespace)

    def hit(self, key: str, window_seconds: int) -> tuple[int, int]:
        result = self._client.eval(_HIT_SCRIPT, 1, self._hit_key(key), int(window_seconds))
        count, reset = list(result)
        return int(count), max(1, int(reset))

    def lock(self, key: str, seconds: int) -> None:
        self._client.set(self._lock_key(key), "1", ex=int(seconds))

    def locked(self, key: str) -> int:
        ttl = int(self._client.ttl(self._lock_key(key)))
        if ttl <= 0:
            return 0
        return ttl

    def clear(self, key: str) -> None:
        self._client.delete(self._hit_key(key), self._lock_key(key))

    def _hit_key(self, key: str) -> str:
        return f"{self._hits_prefix}{key}"

    def _lock_key(self, key: str) -> str:
        return f"{self._locks_prefix}{key}"


class RedisCacheStore(CacheStore):
    """A Redis string cache with one TTL-bound key per Terp cache entry."""

    def __init__(self, client: Any, *, namespace: str = "terp") -> None:
        self._client = client
        self._prefix = f"{namespace}:cache:"
        mark_shared_cache_store(self)

    @classmethod
    def from_url(cls, url: str, *, namespace: str = "terp") -> RedisCacheStore:
        """Create the store from a Redis URL using redis-py's ``Redis.from_url``."""
        return cls(_client_from_url(url), namespace=namespace)

    def get(self, key: str) -> str | None:
        value = self._client.get(self._key(key))
        if value is None:
            return None
        return _text(value)

    def set(self, key: str, value: str, *, ttl_seconds: int) -> None:
        if ttl_seconds <= 0:
            raise ValueError(
                f"RedisCacheStore.set requires a positive ttl_seconds, got {ttl_seconds!r}"
            )
        self._client.set(self._key(key), value, ex=int(ttl_seconds))

    def delete(self, key: str) -> None:
        self._client.delete(self._key(key))

    def _key(self, key: str) -> str:
        return f"{self._prefix}{key}"


@dataclass(frozen=True)
class RedisStoreBundle:
    """Convenience holder for the three Redis-backed kernel store adapters.

    Use this when one Redis deployment backs all three Terp store seams. Separate classes
    remain available for deployments that split cache and control-state Redis clusters.
    Capability-facing adapters (realtime connection tickets, OIDC authorization state)
    live in their own submodules behind optional extras — construct them explicitly.
    """

    idempotency: RedisIdempotencyStore
    throttle: RedisThrottleStore
    cache: RedisCacheStore

    @classmethod
    def from_client(cls, client: Any, *, namespace: str = "terp") -> RedisStoreBundle:
        """Build all three adapters over an already-configured redis-py compatible client."""
        return cls(
            idempotency=RedisIdempotencyStore(client, namespace=namespace),
            throttle=RedisThrottleStore(client, namespace=namespace),
            cache=RedisCacheStore(client, namespace=namespace),
        )

    @classmethod
    def from_url(cls, url: str, *, namespace: str = "terp") -> RedisStoreBundle:
        """Build all three adapters over one Redis client constructed from *url*."""
        return cls.from_client(_client_from_url(url), namespace=namespace)


__all__ = [
    "RedisCacheStore",
    "RedisIdempotencyStore",
    "RedisStoreBundle",
    "RedisThrottleStore",
]
