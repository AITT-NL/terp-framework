"""Redis-backed realtime connection tickets (the ``terp-cap-redis[realtime]`` extra).

The realtime capability's one-use connection tickets are per-process by default; a
multi-replica deployment shares them here so the replica that serves the WebSocket
upgrade can consume a ticket another replica issued. This submodule is the only place
terp-cap-redis touches terp-cap-realtime: importing it requires the ``realtime`` extra
(``terp-cap-redis[realtime]``), so the shared kernel stores in
:mod:`terp.capabilities.redis.stores` never drag a self-registering transport
capability onto the path.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from terp.capabilities.realtime import ConnectionTicket, ConnectionTicketStore
from terp.core import Principal, Role

from terp.capabilities.redis.stores import _client_from_url, _text

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


__all__ = ["RedisConnectionTicketStore"]
