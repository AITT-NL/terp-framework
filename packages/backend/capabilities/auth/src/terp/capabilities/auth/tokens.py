"""Signed JWT access tokens, keyed on a key derived from the kernel ``SECRET_KEY``.

**Key rotation (ADR 0076 §2, amended by ADR 0189).** A token is signed with one key
only: the HS256 key derived from the current ``SECRET_KEY`` under this module's own
HKDF label, so the signing key is never ``SECRET_KEY`` itself and is unrelated to the
keys the sealing domains derive from it. Every other key only *verifies*, and only for
:data:`FALLBACK_VERIFY_WINDOW` after the token's ``iat``: the same derivation of each
``SECRET_KEY_FALLBACKS`` entry, and the form tokens were signed with before the label
existed — the raw secret, current or fallback — so a token issued before an upgrade or
a rotation lives out its normal life and no longer. A retired key cannot be made to
honour a token for longer by the ``exp`` the token claims.
"""

from __future__ import annotations

import base64
import datetime
import enum
import uuid
from dataclasses import dataclass
from typing import Final

import jwt

from terp.core import AuthenticationError, Role, Roles, as_role, derive_key, settings

_ALGORITHM = "HS256"
DEFAULT_ACCESS_TOKEN_TTL = datetime.timedelta(minutes=15)

#: The HKDF label the access-token signing key is derived under (ADR 0189). Versioned:
#: a new derivation is a new label, and this one then verifies only, as a retired key does.
_SIGNING_INFO: Final[bytes] = b"terp.capabilities.auth.access-token.v1"

#: How long after its ``iat`` a token signed under any key but the current one still
#: verifies — the lifetime the framework's own logins give an access token. It is what
#: makes "drop ``SECRET_KEY_FALLBACKS`` after the longest token lifetime" a number the
#: framework enforces rather than one an operator has to know: a fallback stops
#: honouring access tokens this long after the deploy that introduced it, whatever
#: lifetime an app gave a token when it minted one itself.
FALLBACK_VERIFY_WINDOW: Final[datetime.timedelta] = DEFAULT_ACCESS_TOKEN_TTL


class SubjectKind(enum.StrEnum):
    """What the ``sub`` claim identifies — which store owns the subject (ADR 0088).

    A Terp deployment has two kinds of principal: people, and the machines that
    integrate with it. They authenticate differently and are revoked from
    different tables, but they are authorized identically — the same guard, the
    same role rank, the same permission grants.

    Signing the kind is what keeps that honest. The revocation validator must know
    which table holds the subject's epoch, and *inferring* it ("try users, then
    try service accounts") would mean a subject id present in both tables
    resolves by lookup order rather than by what the credential actually is. The
    token says what it represents.
    """

    USER = "user"
    SERVICE = "service"

#: The ``iss`` / ``aud`` claims every Terp access token carries and every decode
#: **requires** (ADR 0076): a JWT minted by any other issuer for any other audience
#: — even one signed with the same shared secret (another service reusing the key,
#: an OIDC provider, a future token type) — is refused, never confused for an
#: access credential.
TOKEN_ISSUER: Final[str] = "terp.auth"  # arch-allow-no-hardcoded-credentials: a public registered claim VALUE, signed into every token and printed in every decode error — secrecy is not what it is for
TOKEN_AUDIENCE: Final[str] = "terp.api"  # arch-allow-no-hardcoded-credentials: as above — the audience this API answers to, public by construction

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
    kind: SubjectKind = SubjectKind.USER
    #: How the session was authenticated (RFC 8176 ``amr``), in the order the
    #: factors were satisfied: ``("pwd",)`` for a password alone, ``("pwd", "otp")``
    #: when a second factor was also proved. Empty for a token minted before this
    #: claim existed, which is the honest answer rather than a guessed one.
    amr: tuple[str, ...] = ()


def create_access_token(
    *,
    subject: uuid.UUID,
    role: Role | Roles,
    tenant: uuid.UUID | None = None,
    token_version: int = 0,
    kind: SubjectKind = SubjectKind.USER,
    amr: tuple[str, ...] = (),
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

    *kind* signs which store owns the subject (ADR 0088), so the revocation
    validator reads the right table's epoch instead of guessing from a lookup
    order. It defaults to a human user, which is what an unmarked legacy token is.

    *amr* signs **how** the session was authenticated (RFC 8176), so a later decision
    can tell a password-only session from one that also proved a second factor. It is
    only signed when non-empty: a token minted without being told carries no claim at
    all, which is the honest shape — an ``amr`` of ``["pwd"]`` asserted by default
    would be an unverified statement about a mint that never checked.

    Every token also signs the fixed :data:`TOKEN_ISSUER` / :data:`TOKEN_AUDIENCE`
    pair (ADR 0076), which :func:`decode_access_token` requires — scoping the
    credential to this framework's API even under a shared signing key. Signing
    always uses the key derived from the **current** ``SECRET_KEY`` (never a fallback).
    """
    typed = as_role(role)
    now = datetime.datetime.now(datetime.UTC)
    payload: dict[str, object] = {
        "sub": str(subject),
        "role": typed.name,
        "rank": typed.rank,
        "tv": token_version,
        "kind": str(kind),
        "iss": TOKEN_ISSUER,
        "aud": TOKEN_AUDIENCE,
        "iat": now,
        "exp": now + expires_in,
    }
    if tenant is not None:
        payload["tenant"] = str(tenant)
    if amr:
        # Omitted rather than emitted empty: a token that says it was authenticated
        # by nothing is a claim, and an absent claim is the truthful shape for a
        # mint that was never told. `AccessTokenClaims.amr` reads the absence as ().
        payload["amr"] = list(amr)
    return jwt.encode(payload, _signing_key(settings.SECRET_KEY), algorithm=_ALGORITHM)


def _signing_key(secret: str) -> str:
    """The HS256 key for access tokens derived from *secret*, as base64 text.

    Text rather than the raw 32 bytes so the HMAC key is plain ASCII to every JWT
    library that might read it, at the same 256 bits of strength.
    """
    return base64.urlsafe_b64encode(derive_key(secret, _SIGNING_INFO)).decode("ascii")


def _verification_keys() -> list[tuple[str, bool]]:
    """Every key a token may verify under, in order, each marked *retired* or not.

    The current derivation first and alone unretired. Then the raw ``SECRET_KEY``,
    which signed every token before the label existed, and each ``SECRET_KEY_FALLBACKS``
    entry in both forms: this release's derivation, then the raw secret an older
    release signed with.
    """
    keys = [(_signing_key(settings.SECRET_KEY), False), (settings.SECRET_KEY, True)]
    for fallback in settings.SECRET_KEY_FALLBACKS:
        keys += [(_signing_key(fallback), True), (fallback, True)]
    return keys


def _within_fallback_window(payload: dict) -> bool:
    """Whether a token verified under a retired key was issued recently enough to honour.

    Counted from ``iat``, which every token is refused without, and bounded by
    :data:`FALLBACK_VERIFY_WINDOW` rather than by ``exp``: the window is the lifetime a
    login gives a token, so a token minted for longer stops at the window like the rest.
    """
    issued = datetime.datetime.fromtimestamp(int(payload["iat"]), datetime.UTC)
    return datetime.datetime.now(datetime.UTC) - issued <= FALLBACK_VERIFY_WINDOW


def _verify(token: str) -> dict:
    """Verify *token* against the current key, then each retired one.

    The current derivation verifies first; a **signature** mismatch (and only that)
    moves on to the next key, so an access token issued just before an upgrade or a
    key rotation stays valid (ADR 0076, ADR 0189). A token that verifies under a
    retired key is honoured only inside :data:`FALLBACK_VERIFY_WINDOW` of its ``iat``.
    Any other verification failure — expired, wrong ``aud``/``iss``, a missing
    required claim — is final and never retried against another key.
    """
    rejected: jwt.InvalidSignatureError | None = None
    for key, retired in _verification_keys():
        try:
            payload = jwt.decode(
                token,
                key,
                algorithms=[_ALGORITHM],
                audience=TOKEN_AUDIENCE,
                issuer=TOKEN_ISSUER,
                options={"require": list(_REQUIRED_CLAIMS)},
            )
        except jwt.InvalidSignatureError as exc:
            rejected = exc
            continue
        except jwt.PyJWTError as exc:
            raise AuthenticationError() from exc
        if retired and not _within_fallback_window(payload):
            raise AuthenticationError()
        return payload
    raise AuthenticationError() from rejected


def decode_access_token(token: str) -> AccessTokenClaims:
    """Verify + decode *token*. Raises :class:`AuthenticationError` if invalid.

    Verification is fail-closed on the registered claims: the signature (current
    key or a rotation fallback), the ``exp``/``iat`` lifetime, and the exact
    :data:`TOKEN_ISSUER` / :data:`TOKEN_AUDIENCE` pair must all hold.

    A missing ``kind`` reads as :attr:`SubjectKind.USER` — what every token minted
    before ADR 0088 is — so a key rotation is the only thing that ever invalidates
    a token in flight. A ``kind`` this build does not know is **refused** rather
    than coerced to a default, so a subject type only this framework can mint
    never degrades into the one with the broadest reach.
    """
    payload = _verify(token)
    try:
        raw_tenant = payload.get("tenant")
        return AccessTokenClaims(
            subject=uuid.UUID(payload["sub"]),
            role=Role(str(payload["role"]), int(payload["rank"])),
            tenant=uuid.UUID(raw_tenant) if raw_tenant is not None else None,
            token_version=int(payload.get("tv", 0)),
            kind=SubjectKind(str(payload.get("kind", SubjectKind.USER))),
            # Absent claim -> empty tuple. A token minted before this claim existed says
            # nothing about how it was obtained, and reading that silence as "password"
            # would invent a fact the signature does not carry.
            amr=tuple(str(method) for method in payload.get("amr", ())),
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise AuthenticationError() from exc


__all__ = [
    "AccessTokenClaims",
    "DEFAULT_ACCESS_TOKEN_TTL",
    "FALLBACK_VERIFY_WINDOW",
    "TOKEN_AUDIENCE",
    "TOKEN_ISSUER",
    "SubjectKind",
    "create_access_token",
    "decode_access_token",
]
