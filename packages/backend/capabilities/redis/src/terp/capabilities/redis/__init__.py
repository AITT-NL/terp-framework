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
* ``terp-cap-redis[all]`` — both capability-facing adapters.

Both re-export lazily from the package root: importing them without the matching extra
raises a directive ``ModuleNotFoundError`` naming the extra to install. They are omitted
from ``__all__`` so a wildcard import remains valid for a base-only installation.
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
    "RedisConnectionTicketStore": (
        "terp.capabilities.redis.realtime",
        "terp.capabilities.realtime",
        "realtime",
    ),
    "RedisOIDCStateStore": (
        "terp.capabilities.redis.oidc",
        "terp.capabilities.oidc",
        "oidc",
    ),
}


def __getattr__(name: str) -> Any:
    extra = _EXTRA_EXPORTS.get(name)
    if extra is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    module_name, required_module, extra_name = extra
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name != required_module:
            raise
        raise ModuleNotFoundError(
            f"{name} requires the optional `{extra_name}` adapter; "
            f"install `terp-cap-redis[{extra_name}]` (or `terp-cap-redis[all]`).",
            name=required_module,
        ) from exc
    return getattr(module, name)


__all__ = [
    "RedisCacheStore",
    "RedisIdempotencyStore",
    "RedisStoreBundle",
    "RedisThrottleStore",
]
