"""Refresh-token mechanics for the auth capability (ADR 0054).

Auth owns the *mechanics* of the refresh credential — how a token is generated, how it is
digested for storage, and how it rides an httpOnly cookie — but **not** where it is stored:
the row lives in the identity store, reached through the app-wired refresh seams (symmetric
with ``authenticate`` / ``token_version_resolver``), so auth never imports identity.

The refresh token is opaque, 256-bit ``secrets`` randomness (not a JWT — its only meaning is
"this row is still live", which is what makes it individually revocable). It is stored as a
**keyed HMAC-SHA256 digest**: the key is derived from the app ``SECRET_KEY`` with domain
separation, so a database leak alone cannot use or even confirm a token without the app
secret, while the digest stays deterministic — one indexed lookup on ``/refresh``.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass

from fastapi import Response

from terp.core import settings

# 32 bytes = 256 bits of entropy; url-safe so it is a valid cookie value verbatim.
_TOKEN_NBYTES = 32
# Domain-separates the refresh-digest key from every other use of SECRET_KEY.
_DIGEST_CONTEXT = b"terp.refresh-token.v1"


@dataclass(frozen=True)
class RefreshRotation:
    """The outcome of a successful refresh: whose session, and the new token to re-cookie."""

    user_id: uuid.UUID
    token: str


def generate_refresh_token() -> str:
    """A fresh opaque refresh token — 256 bits of URL-safe randomness."""
    return secrets.token_urlsafe(_TOKEN_NBYTES)


def refresh_token_digest(raw_token: str) -> str:
    """The at-rest digest of *raw_token*: a SECRET_KEY-keyed (peppered) HMAC-SHA256 hex.

    Keyed so a leaked database of digests is useless without the app secret; deterministic
    so ``/refresh`` looks the row up in one indexed read. The key is derived from
    ``SECRET_KEY`` (read at call time, so tests and rotation see the live value) with a
    context prefix, keeping it separate from the access-token signing use of the secret.
    """
    key = hashlib.sha256(_DIGEST_CONTEXT + b":" + settings.SECRET_KEY.encode()).digest()
    return hmac.new(key, raw_token.encode(), hashlib.sha256).hexdigest()


def set_refresh_cookie(response: Response, token: str) -> None:
    """Attach the rotating refresh token as an httpOnly, path-scoped cookie (ADR 0054)."""
    response.set_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        value=token,
        max_age=settings.REFRESH_FAMILY_TTL_SECONDS,
        path=settings.REFRESH_COOKIE_PATH,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite=settings.REFRESH_COOKIE_SAMESITE,
    )


def clear_refresh_cookie(response: Response) -> None:
    """Delete the refresh cookie (logout) — matched on name + path so the browser drops it."""
    response.delete_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        path=settings.REFRESH_COOKIE_PATH,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite=settings.REFRESH_COOKIE_SAMESITE,
    )


__all__ = [
    "RefreshRotation",
    "clear_refresh_cookie",
    "generate_refresh_token",
    "refresh_token_digest",
    "set_refresh_cookie",
]
