"""The auth ``get_principal`` provider — turns a Bearer JWT into a ``Principal``.

This is the implementation that fills the kernel's ``get_principal`` seam: pass
it as ``create_app(..., principal_provider=get_principal)``. A missing or invalid
token yields ``None`` (unauthenticated), which the deny-by-default guard turns
into HTTP 401.

Two providers are offered:

* :func:`get_principal` — the **stateless** default: it trusts a validly-signed,
  unexpired token for its whole lifetime (no store lookup). Simple and zero
  per-request DB cost, at the price of the access-TTL staleness window.
* :func:`build_get_principal` — the **revocable** provider (ADR 0031): it runs an
  app-supplied ``TokenValidator`` against the store every request, so a token whose
  user was deactivated, demoted, re-tenanted, password-reset, or logged out is
  rejected mid-session. Auth owns the *seam* and never imports the store; the app
  wires the implementation (e.g. ``IdentityService(...).token_is_current``), exactly
  as it wires ``authenticate`` and ``tenant_resolver``.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import Request
from sqlmodel import Session

from terp.core import (
    AuthenticationError,
    Principal,
    SessionDep,
    mark_token_revocation_provider,
)

from terp.capabilities.auth.tokens import AccessTokenClaims, decode_access_token

_BEARER_PREFIX = "bearer "

# The app-wired validity check the revocable provider consults every request: given the
# request session and the decoded claims, return whether the token is still valid (the
# subject is active and its token epoch is current). Auth owns the type; the app supplies
# the implementation, so auth never imports the user store (symmetric with the
# ``authenticate`` / ``tenant_resolver`` seams).
TokenValidator = Callable[[Session, AccessTokenClaims], bool]


def _bearer_token(request: Request) -> str | None:
    """Return the raw ``Authorization: Bearer`` token, or ``None`` if absent."""
    header = request.headers.get("Authorization")
    if not header or not header.lower().startswith(_BEARER_PREFIX):
        return None
    return header[len(_BEARER_PREFIX):].strip()


def get_principal(request: Request) -> Principal | None:
    """Extract the caller's principal from the ``Authorization: Bearer`` header.

    The stateless provider: it does **no** per-request store lookup, so an already-issued
    token stays valid until it expires. Use :func:`build_get_principal` for prompt
    revocation (deactivate / demote / password-reset / logout taking effect mid-session).
    """
    token = _bearer_token(request)
    if token is None:
        return None
    try:
        claims = decode_access_token(token)
    except AuthenticationError:
        return None
    return Principal(id=claims.subject, role=claims.role)


def build_get_principal(
    token_validator: TokenValidator | None = None,
) -> Callable[..., Principal | None]:
    """Build a ``get_principal`` seam that re-validates the token against the store.

    When *token_validator* is supplied, the returned provider rejects (→ ``None`` → 401)
    a token the validator fails — the runtime half of the session-revocation control
    (ADR 0031). The provider depends on the request ``Session`` so the validator can do
    its one indexed lookup (the guard already opens a session per guarded request, so
    there is no extra cost there). The returned provider is **marked** as
    revocation-enforcing (:func:`~terp.core.mark_token_revocation_provider`), so
    ``create_app(require_token_revocation=True)`` accepts it and refuses the stateless
    default. With no validator it behaves like :func:`get_principal` (stateless) and is
    left unmarked.
    """

    def get_principal(request: Request, session: SessionDep) -> Principal | None:
        token = _bearer_token(request)
        if token is None:
            return None
        try:
            claims = decode_access_token(token)
        except AuthenticationError:
            return None
        if token_validator is not None and not token_validator(session, claims):
            return None
        return Principal(id=claims.subject, role=claims.role)

    if token_validator is not None:
        mark_token_revocation_provider(get_principal)
    return get_principal


def build_realtime_validator() -> Callable[[Principal, str], bool]:
    """Validate the server-retained bearer behind a realtime connection ticket.

    Native transports cannot send the Authorization header after the generated
    client mints their one-use ticket. The ticket retains the credential only
    in server-side TTL state; this validator rechecks signature/expiry and that
    its subject+role still match the captured principal. Store-backed epoch /
    active-user revocation is an app concern (it owns the identity store):
    compose this validator inside the realtime capability's
    ``principal_validator`` with the app's own fresh-session check.
    """

    def validate(principal: Principal, credential: str) -> bool:
        if not credential:
            return False
        try:
            claims = decode_access_token(credential)
        except AuthenticationError:
            return False
        return claims.subject == principal.id and claims.role == principal.role

    return validate


def tenant_from_bearer(request: Request) -> uuid.UUID | None:
    """Resolve the signed ``tenant`` claim from the request's Bearer token.

    A ready-made resolver for ``terp.capabilities.tenancy.TenantMiddleware``: the
    tenant is only as trustworthy as the token that carries it. A missing,
    invalid, or tenant-less token resolves to ``None`` — scoped services then fail
    closed rather than leaking another tenant's rows.
    """
    token = _bearer_token(request)
    if token is None:
        return None
    try:
        return decode_access_token(token).tenant
    except AuthenticationError:
        return None


__all__ = [
    "TokenValidator",
    "build_get_principal",
    "build_realtime_validator",
    "get_principal",
    "tenant_from_bearer",
]
