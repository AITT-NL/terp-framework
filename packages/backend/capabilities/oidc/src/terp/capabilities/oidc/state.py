"""Single-use, TTL-bounded authorization state (ADR 0058).

Every ``/authorize`` issues a fresh ``state`` (the CSRF binder), ``nonce`` (bound
into the ID token), and PKCE ``code_verifier`` — all from ``secrets`` — and parks
them here until the callback presents the ``state`` back. ``consume`` is strictly
single-use (a replayed state finds nothing) and expiring (an abandoned flow ages
out), so a captured callback URL cannot be replayed and the store cannot grow
without bound. In-memory and per-process by default — an authorization flow is
short-lived, so per-instance state suffices behind a sticky or single-API setup; a
multi-instance deployment swaps in a shared :class:`OIDCStateStore` implementation
(e.g. ``terp.capabilities.redis.oidc.RedisOIDCStateStore``) so any replica can
finish a flow another replica opened.
"""

from __future__ import annotations

import datetime
import hashlib
import secrets
from threading import Lock
from base64 import urlsafe_b64encode
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

DEFAULT_STATE_TTL = datetime.timedelta(minutes=10)


def _utc_now() -> datetime.datetime:
    """UTC ``now`` provider — private so tests can monkeypatch the clock."""
    return datetime.datetime.now(datetime.UTC)


@dataclass(frozen=True)
class PendingAuthorization:
    """One in-flight authorization: what the callback must match against."""

    provider: str
    nonce: str
    code_verifier: str
    expires_at: datetime.datetime


def generate_code_verifier() -> str:
    """A high-entropy PKCE code verifier (RFC 7636 §4.1)."""
    return secrets.token_urlsafe(64)


def code_challenge_s256(verifier: str) -> str:
    """The S256 code challenge for *verifier* (RFC 7636 §4.2): base64url(sha256), unpadded."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


@runtime_checkable
class OIDCStateStore(Protocol):
    """The single-use authorization-state port every state store implements.

    The router only ever calls these two methods, so a deployment picks its scope by
    implementation: the default :class:`InMemoryStateStore` is per-process (one API
    replica or sticky routing); a shared implementation (e.g. the Redis-backed store in
    ``terp-cap-redis[oidc]``) lets any replica finish a flow another replica opened.
    Every implementation must keep ``consume`` strictly single-use, expiring, and
    provider-matched.
    """

    def issue(self, provider: str) -> tuple[str, PendingAuthorization]:
        """Open a new flow for *provider*: returns ``(state, pending)``."""
        ...

    def consume(self, state: str, provider: str) -> PendingAuthorization | None:
        """Redeem *state* exactly once, or ``None`` (unknown / expired / wrong provider)."""
        ...


class InMemoryStateStore:
    """The default per-process single-use state store."""

    def __init__(self, *, ttl: datetime.timedelta = DEFAULT_STATE_TTL) -> None:
        self._ttl = ttl
        self._pending: dict[str, PendingAuthorization] = {}
        self._lock = Lock()

    def issue(self, provider: str) -> tuple[str, PendingAuthorization]:
        """Open a new flow for *provider*: returns ``(state, pending)``."""
        state = secrets.token_urlsafe(32)
        pending = PendingAuthorization(
            provider=provider,
            nonce=secrets.token_urlsafe(32),
            code_verifier=generate_code_verifier(),
            expires_at=_utc_now() + self._ttl,
        )
        with self._lock:
            self._prune()
            self._pending[state] = pending
        return state, pending

    def consume(self, state: str, provider: str) -> PendingAuthorization | None:
        """Redeem *state* exactly once, or ``None`` (unknown / expired / wrong provider).

        The provider match refuses a cross-provider splice: a state issued for one
        provider cannot finish another provider's callback.
        """
        with self._lock:
            pending = self._pending.pop(state, None)
        if pending is None or pending.provider != provider:
            return None
        if pending.expires_at <= _utc_now():
            return None
        return pending

    def _prune(self) -> None:
        """Drop expired flows (called under the lock) so abandoned logins age out."""
        now = _utc_now()
        for key in [k for k, v in self._pending.items() if v.expires_at <= now]:
            del self._pending[key]


__all__ = [
    "DEFAULT_STATE_TTL",
    "InMemoryStateStore",
    "OIDCStateStore",
    "PendingAuthorization",
    "code_challenge_s256",
    "generate_code_verifier",
]
