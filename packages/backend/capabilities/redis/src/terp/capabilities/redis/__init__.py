"""terp.capabilities.redis — shared Redis-backed stores for horizontal deployments.

Terp's kernel deliberately keeps the idempotency, throttling, and cache ports engine-free:
``terp.core`` ships safe per-process defaults and boot guards, while a deployment that runs
more than one replica wires a shared backend explicitly. This capability is that opt-in
backend for Redis. It has no routes, models, or migrations; it is a library adapter a
composition root constructs from either an existing redis-py client or a Redis URL and then
passes to ``create_app``::

    stores = RedisStoreBundle.from_url(settings.REDIS_URL)
    create_app(
        ...,
        idempotency_store=stores.idempotency,
        throttle_store=stores.throttle,
        cache_store=stores.cache,
        require_shared_idempotency_store=settings.is_production,
        require_shared_throttle_store=settings.is_production,
        require_shared_cache_store=settings.is_production,
    )

The adapters stamp themselves with the public ``mark_shared_*`` markers so the kernel's
multi-instance boot promises are checked fail-closed. Redis operations are intentionally
small and TTL-bound: idempotency claims and throttle counters use Lua scripts for atomicity;
cache values use Redis' native string TTLs.
"""

from __future__ import annotations

from terp.capabilities.redis.stores import (
    RedisCacheStore,
    RedisConnectionTicketStore,
    RedisIdempotencyStore,
    RedisStoreBundle,
    RedisThrottleStore,
)

__all__ = [
    "RedisCacheStore",
    "RedisConnectionTicketStore",
    "RedisIdempotencyStore",
    "RedisStoreBundle",
    "RedisThrottleStore",
]
