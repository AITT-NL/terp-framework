"""Single-use, TTL-bounded connection tickets for browser-native transports.

The Terp access token lives in React memory. Native ``EventSource`` and
``WebSocket`` constructors cannot attach its Authorization header, and putting
the bearer token in a URL would leak it into logs/history. The sanctioned flow
therefore mints a short-lived opaque ticket over the generated authenticated
client, then redeems it exactly once at the transport handshake.
"""

from __future__ import annotations

import secrets
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock

from terp.core import Principal


@dataclass(frozen=True)
class ConnectionTicket:
    """The authority captured at mint for one channel + transport handshake."""

    principal: Principal
    channel: str
    transport: str
    credential: str = ""
    audience: str = ""


class ConnectionTicketStore(ABC):
    """Atomic issue/consume port for opaque one-use tickets."""

    @abstractmethod
    def issue(self, ticket: ConnectionTicket, *, ttl_seconds: int) -> str: ...

    @abstractmethod
    def consume(
        self, token: str, *, channel: str, transport: str
    ) -> ConnectionTicket | None:
        """Atomically remove and return a live exact-match ticket, else None."""


class InMemoryConnectionTicketStore(ConnectionTicketStore):
    """Thread-safe per-process ticket store, TTL-expired on issue/consume."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = Lock()
        self._entries: dict[str, tuple[float, ConnectionTicket]] = {}

    def issue(self, ticket: ConnectionTicket, *, ttl_seconds: int) -> str:
        if ttl_seconds <= 0:
            raise ValueError("connection ticket ttl_seconds must be positive")
        token = secrets.token_urlsafe(32)
        now = self._clock()
        with self._lock:
            self._sweep(now)
            self._entries[token] = (now + ttl_seconds, ticket)
        return token

    def consume(
        self, token: str, *, channel: str, transport: str
    ) -> ConnectionTicket | None:
        now = self._clock()
        with self._lock:
            entry = self._entries.pop(token, None)
            if entry is None:
                return None
            expires_at, ticket = entry
            if expires_at <= now:
                return None
            # Consume even on a mismatch: a leaked ticket cannot be probed
            # against channel names/transports and then reused correctly.
            if ticket.channel != channel or ticket.transport != transport:
                return None
            return ticket

    def _sweep(self, now: float) -> None:
        expired = [key for key, (expires_at, _) in self._entries.items() if expires_at <= now]
        for key in expired:
            del self._entries[key]

    def reset(self) -> None:
        with self._lock:
            self._entries.clear()


_configured_store: ConnectionTicketStore | None = None
_configuration_lock = Lock()


def configure_ticket_store(store: ConnectionTicketStore | None) -> None:
    """Install *store* process-wide (``None`` resets to the lazy default)."""
    global _configured_store
    with _configuration_lock:
        _configured_store = store


def get_ticket_store() -> ConnectionTicketStore:
    """The configured store, creating the in-memory default lazily."""
    global _configured_store
    with _configuration_lock:
        if _configured_store is None:
            _configured_store = InMemoryConnectionTicketStore()
        return _configured_store


__all__ = [
    "ConnectionTicket",
    "ConnectionTicketStore",
    "InMemoryConnectionTicketStore",
    "configure_ticket_store",
    "get_ticket_store",
]
