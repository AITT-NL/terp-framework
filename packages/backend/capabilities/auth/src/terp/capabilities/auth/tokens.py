"""Signed JWT access tokens, keyed on the kernel ``SECRET_KEY``."""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass
from typing import Final

import jwt

from terp.core import AuthenticationError, Role, Roles, as_role, settings

_ALGORITHM = "HS256"
DEFAULT_ACCESS_TOKEN_TTL = datetime.timedelta(minutes=15)

#: The ``iss`` / ``aud`` claims every Terp access token carries and every decode
#: **requires** (ADR 0076): a JWT minted by any other issuer for any other audience
#: — even one signed with the same shared secret (another service reusing the key,
#: an OIDC provider, a future token type) — is refused, never confused for an
#: access credential.
TOKEN_ISSUER: Final[str] = "terp.auth"
TOKEN_AUDIENCE: Final[str] = "terp.api"

# Every claim an access token is refused without: the registered pair above plus
# the identity/lifetime pair — a token missing any of them never authenticates.
_REQUIRED_CLAIMS: Final[tuple[str, ...]] = ("exp", "iat", "sub", "aud", "iss")


@dataclass(frozen=True)
class AccessTokenClaims:
    """The trusted claims carried by a decoded access token."""

    subject: uuid.UUID
    role: Role
    tenant: uuid.UUID | None = None
    token_version: int = 0


def create_access_token(
    *,
    subject: uuid.UUID,
    role: Role | Roles,
    tenant: uuid.UUID | None = None,
    token_version: int = 0,
    expires_in: datetime.timedelta = DEFAULT_ACCESS_TOKEN_TTL,
) -> str:
    """Issue a short-lived HS256 access token for *subject* with *role*.

    *role* may be a typed :class:`~terp.core.Role` or the legacy ``Roles`` enum;
    its name and rank are both signed in, so a consumer-defined role round-trips
    without being coerced to a fixed tier. When *tenant* is given it is signed as
    the ``tenant`` claim, so a tenant-aware app can bind request scope from the
    verified token (see ``terp.capabilities.tenancy.TenantMiddleware``).

    *token_version* signs the subject's current **token epoch** as the ``tv`` claim
    (ADR 0031). A principal provider wired with a validator rejects the token once the
    stored epoch moves past it, so deactivating, demoting, re-tenanting, resetting the
    password of, or logging out a user invalidates their outstanding tokens at once —
    sign the user's current epoch here (default ``0`` = revocation inactive).

    Every token also signs the fixed :data:`TOKEN_ISSUER` / :data:`TOKEN_AUDIENCE`
    pair (ADR 0076), which :func:`decode_access_token` requires — scoping the
    credential to this framework's API even under a shared signing key. Signing
    always uses the **current** ``SECRET_KEY`` (never a fallback).
    """
    typed = as_role(role)
    now = datetime.datetime.now(datetime.UTC)
    payload: dict[str, object] = {
        "sub": str(subject),
        "role": typed.name,
        "rank": typed.rank,
        "tv": token_version,
        "iss": TOKEN_ISSUER,
        "aud": TOKEN_AUDIENCE,
        "iat": now,
        "exp": now + expires_in,
    }
    if tenant is not None:
        payload["tenant"] = str(tenant)
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=_ALGORITHM)


def _verify(token: str) -> dict:
    """Verify *token* against the current key, then each rotation fallback.

    ``SECRET_KEY`` verifies first; a **signature** mismatch (and only that) moves
    on to the next ``SECRET_KEY_FALLBACKS`` entry, so an access token issued just
    before a key rotation stays valid through the configured window (ADR 0076).
    Any other verification failure — expired, wrong ``aud``/``iss``, a missing
    required claim — is final and never retried against another key.
    """
    keys = (settings.SECRET_KEY, *settings.SECRET_KEY_FALLBACKS)
    rejected: jwt.InvalidSignatureError | None = None
    for key in keys:
        try:
            return jwt.decode(
                token,
                key,
                algorithms=[_ALGORITHM],
                audience=TOKEN_AUDIENCE,
                issuer=TOKEN_ISSUER,
                options={"require": list(_REQUIRED_CLAIMS)},
            )
        except jwt.InvalidSignatureError as exc:
            rejected = exc
        except jwt.PyJWTError as exc:
            raise AuthenticationError() from exc
    raise AuthenticationError() from rejected


def decode_access_token(token: str) -> AccessTokenClaims:
    """Verify + decode *token*. Raises :class:`AuthenticationError` if invalid.

    Verification is fail-closed on the registered claims: the signature (current
    key or a rotation fallback), the ``exp``/``iat`` lifetime, and the exact
    :data:`TOKEN_ISSUER` / :data:`TOKEN_AUDIENCE` pair must all hold.
    """
    payload = _verify(token)
    try:
        raw_tenant = payload.get("tenant")
        return AccessTokenClaims(
            subject=uuid.UUID(payload["sub"]),
            role=Role(str(payload["role"]), int(payload["rank"])),
            tenant=uuid.UUID(raw_tenant) if raw_tenant is not None else None,
            token_version=int(payload.get("tv", 0)),
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise AuthenticationError() from exc


__all__ = [
    "AccessTokenClaims",
    "DEFAULT_ACCESS_TOKEN_TTL",
    "TOKEN_AUDIENCE",
    "TOKEN_ISSUER",
    "create_access_token",
    "decode_access_token",
]
