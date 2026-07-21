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

Two capability-facing adapters live behind optional extras, so the base distribution
depends only on ``terp-core`` (shared throttling/idempotency never installs another
capability):

* ``terp-cap-redis[realtime]`` — :class:`RedisConnectionTicketStore`
  (:mod:`terp.capabilities.redis.realtime`), shared one-use realtime connection tickets.
* ``terp-cap-redis[oidc]`` — :class:`RedisOIDCStateStore`
  (:mod:`terp.capabilities.redis.oidc`), shared single-use OIDC authorization state for
  multi-replica SSO.

Both re-export lazily from the package root: importing them without the matching extra
raises the underlying ``ModuleNotFoundError`` for the missing capability.
"""

from __future__ import annotations

from typing import Any

from terp.capabilities.redis.stores import (
    RedisCacheStore,
    RedisIdempotencyStore,
    RedisStoreBundle,
    RedisThrottleStore,
)

# The extras' adapters import their capability at module import time, so they resolve
# lazily here: the base install (no extras) can `import terp.capabilities.redis` freely.
_EXTRA_EXPORTS = {
    "RedisConnectionTicketStore": "terp.capabilities.redis.realtime",
    "RedisOIDCStateStore": "terp.capabilities.redis.oidc",
}


def __getattr__(name: str) -> Any:
    module_name = _EXTRA_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    return getattr(importlib.import_module(module_name), name)


__all__ = [
    "RedisCacheStore",
    "RedisConnectionTicketStore",
    "RedisIdempotencyStore",
    "RedisOIDCStateStore",
    "RedisStoreBundle",
    "RedisThrottleStore",
]
