"""Sealed, expiring, single-use account tokens (ADR 0196).

A token is what a self-service mail carries: the proof that whoever redeems it reads that
address. Two layers hold it.

**The token is sealed.** It is a ``SealingDomain`` value under a key of its own derived from
``SECRET_KEY``, so its content (the purpose, the expiry, and what redeeming it needs) can be
neither read nor forged without the app's secret, and it rotates like every sealed value. A
sign-up token carries the address and the password's hash, never the password, so nothing
personal is stored before the account exists.

**Its row makes it single-use.** :class:`AccountTokenService` writes one
:class:`~terp.capabilities.identity.AccountToken` per request, holding only a keyed digest
of the token, and redeeming stamps ``used_at``. Writing that row is the audited write the
mail is queued on, so with the durable outbox the mail commits, or rolls back, with it
(ADR 0150).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlmodel import Session

from terp.core import AuditAction, BaseSchema, BaseService, BaseUpdateSchema, SealingDomain, settings

from terp.capabilities.identity import AccountToken

#: The purposes a token is sealed for; one never opens as another.
SIGN_UP = "sign_up"
RESET = "reset"

_DOMAIN = SealingDomain("users.account", b"terp.users.account-token.v1")
_DIGEST_CONTEXT = b"terp.users.account-token-digest.v1"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    """A stored datetime as timezone-aware UTC (SQLite may hand it back naive)."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def seal_account_token(purpose: str, claims: Mapping[str, Any], *, ttl: timedelta) -> str:
    """A sealed token for *purpose*, expiring *ttl* from now, carrying *claims*."""
    expires = int((_utc_now() + ttl).timestamp())
    body = json.dumps({**claims, "p": purpose, "x": expires}, sort_keys=True, separators=(",", ":"))
    return _DOMAIN.seal(body)


def open_account_token(purpose: str, token: str) -> dict[str, Any] | None:
    """The claims of *token*, or ``None`` when it is not a live token for *purpose*.

    ``None`` covers a token no key opens, a damaged one, one sealed for another purpose and
    an expired one alike, so a caller answers all of them the same way.
    """
    opened = _DOMAIN.open(token)
    if opened is None:
        return None
    try:
        claims = json.loads(opened[0])
    except ValueError:
        return None
    if not isinstance(claims, dict) or claims.get("p") != purpose:
        return None
    expires = claims.get("x")
    if not isinstance(expires, int) or expires < _utc_now().timestamp():
        return None
    return claims


def _digest(token: str, secret: str) -> str:
    key = hashlib.sha256(_DIGEST_CONTEXT + b":" + secret.encode()).digest()
    return hmac.new(key, token.encode(), hashlib.sha256).hexdigest()


def account_token_digests(token: str) -> tuple[str, ...]:
    """Every digest *token* may be stored under, the current key's first.

    As a refresh token's is (ADR 0189): a row stored before a key rotation is still found
    under a ``SECRET_KEY_FALLBACKS`` key, so a rotation does not void a link mailed a minute
    before it.
    """
    return (
        _digest(token, settings.SECRET_KEY),
        *(_digest(token, fallback) for fallback in settings.SECRET_KEY_FALLBACKS),
    )


class _NoInput(BaseSchema):
    """Account tokens are written by this service's own methods, never from a request body."""


class _NoUpdate(BaseUpdateSchema):
    """No field of an account token is edited; redeeming one is :meth:`consume`."""


class AccountTokenService(BaseService[AccountToken, _NoInput, _NoUpdate]):
    """Record and redeem account tokens through the audited write boundary."""

    model = AccountToken

    def record(
        self,
        session: Session,
        token: str,
        *,
        purpose: str,
        ttl: timedelta,
        user_id: uuid.UUID | None = None,
    ) -> AccountToken:
        """Store *token*'s digest; this audited write is the one its mail commits with."""
        row = AccountToken(
            purpose=purpose,
            token_hash=account_token_digests(token)[0],
            user_id=user_id,
            expires_at=_utc_now() + ttl,
        )
        return self._save(session, row, AuditAction.CREATED)

    def live(self, session: Session, token: str, *, purpose: str) -> AccountToken | None:
        """The unused, unexpired row for *token* and *purpose*, or ``None``."""
        row = session.exec(
            self.base_query().where(
                AccountToken.token_hash.in_(account_token_digests(token))  # type: ignore[attr-defined]
            )
        ).first()
        if row is None or row.purpose != purpose or row.used_at is not None:
            return None
        if _as_utc(row.expires_at) < _utc_now():
            return None
        return row

    def consume(self, session: Session, row: AccountToken) -> None:
        """Spend *row*: the token it belongs to never redeems again."""
        row.used_at = _utc_now()
        self._save(session, row, AuditAction.UPDATED)


__all__ = [
    "RESET",
    "SIGN_UP",
    "AccountTokenService",
    "account_token_digests",
    "open_account_token",
    "seal_account_token",
]
