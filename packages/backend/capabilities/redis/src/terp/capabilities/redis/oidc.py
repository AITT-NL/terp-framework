"""Redis-backed OIDC authorization state (the ``terp-cap-redis[oidc]`` extra).

The OIDC capability's default :class:`~terp.capabilities.oidc.InMemoryStateStore` is
per-process, so out of the box SSO needs one API replica or sticky routing. This store
implements the same :class:`~terp.capabilities.oidc.OIDCStateStore` port over Redis:
the ``/authorize`` and ``/callback`` halves of a flow may then land on different
replicas. ``consume`` keeps the port's guarantees — strictly single-use (an atomic
GET+DEL), expiring (a native Redis TTL bounds every pending flow), and
provider-matched (a state issued for one provider cannot finish another's callback).

Importing this submodule requires the ``oidc`` extra (``terp-cap-redis[oidc]``); the
shared kernel stores in :mod:`terp.capabilities.redis.stores` stay decoupled from it.
"""

from __future__ import annotations

import datetime
import json
import secrets
from typing import Any

from terp.capabilities.oidc import (
    DEFAULT_STATE_TTL,
    PendingAuthorization,
    generate_code_verifier,
)

from terp.capabilities.redis.stores import _client_from_url, _text

_CONSUME_STATE_SCRIPT = """
local value = redis.call('GET', KEYS[1])
if not value then
    return nil
end
redis.call('DEL', KEYS[1])
return value
"""


class RedisOIDCStateStore:
    """A shared, single-use OIDC state store for multi-replica deployments."""

    def __init__(
        self,
        client: Any,
        *,
        namespace: str = "terp",
        ttl: datetime.timedelta = DEFAULT_STATE_TTL,
    ) -> None:
        ttl_seconds = int(ttl.total_seconds())
        if ttl_seconds <= 0:
            raise ValueError("RedisOIDCStateStore requires a positive ttl")
        self._client = client
        self._prefix = f"{namespace}:oidc-state:"
        self._ttl = datetime.timedelta(seconds=ttl_seconds)

    @classmethod
    def from_url(
        cls,
        url: str,
        *,
        namespace: str = "terp",
        ttl: datetime.timedelta = DEFAULT_STATE_TTL,
    ) -> RedisOIDCStateStore:
        """Create the store from a Redis URL using redis-py's ``Redis.from_url``."""
        return cls(_client_from_url(url), namespace=namespace, ttl=ttl)

    def issue(self, provider: str) -> tuple[str, PendingAuthorization]:
        """Open a new flow for *provider*: returns ``(state, pending)``."""
        state = secrets.token_urlsafe(32)
        pending = PendingAuthorization(
            provider=provider,
            nonce=secrets.token_urlsafe(32),
            code_verifier=generate_code_verifier(),
            expires_at=datetime.datetime.now(datetime.UTC) + self._ttl,
        )
        value = json.dumps(
            {
                "provider": pending.provider,
                "nonce": pending.nonce,
                "code_verifier": pending.code_verifier,
                "expires_at": pending.expires_at.isoformat(),
            },
            separators=(",", ":"),
        )
        # The Redis TTL is the expiry: an abandoned flow ages out server-side, so the
        # store cannot grow without bound and a replica never sees a stale state.
        self._client.set(self._key(state), value, ex=int(self._ttl.total_seconds()))
        return state, pending

    def consume(self, state: str, provider: str) -> PendingAuthorization | None:
        """Redeem *state* exactly once, or ``None`` (unknown / expired / wrong provider)."""
        raw = self._client.eval(_CONSUME_STATE_SCRIPT, 1, self._key(state))
        if raw is None:
            return None
        payload = json.loads(_text(raw))
        pending = PendingAuthorization(
            provider=payload["provider"],
            nonce=payload["nonce"],
            code_verifier=payload["code_verifier"],
            expires_at=datetime.datetime.fromisoformat(payload["expires_at"]),
        )
        if pending.provider != provider:
            return None
        if pending.expires_at <= datetime.datetime.now(datetime.UTC):
            return None
        return pending

    def _key(self, state: str) -> str:
        return f"{self._prefix}{state}"


__all__ = ["RedisOIDCStateStore"]
