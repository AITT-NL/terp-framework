"""The app-wired seams the login router is built from (ADR 0013, 0031, 0054, 0088).

Auth owns the mechanics of a session and none of the stores behind it, so every store
operation it needs is a callable the composition root hands in: these are their shapes.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from sqlmodel import Session

from terp.core import Principal

from terp.capabilities.auth.refresh import RefreshRotation
from terp.capabilities.auth.schemas import CurrentUser

Authenticator = Callable[[Session, str, str], Principal | None]
LoginTenantResolver = Callable[[Session, Principal], uuid.UUID | None]
# Resolve the subject's current token epoch so login signs it (see module docstring).
TokenVersionResolver = Callable[[Session, Principal], int]
# Revoke (invalidate) a subject's outstanding tokens — the logout write-back, app-wired
# to the store (e.g. ``UsersService.revoke_sessions``) since auth does not own it.
TokenRevoker = Callable[[Session, uuid.UUID], None]
# Refresh-token seams (ADR 0054), app-wired to the identity refresh store so auth never
# imports it. Issue the first token at login; rotate (single-use + reuse-detect) a presented
# token; resolve an ACTIVE subject's principal by id (the /refresh analog of authenticate,
# which needs a password). All three are wired together or not at all.
RefreshIssuer = Callable[[Session, uuid.UUID], str]
RefreshRotator = Callable[[Session, str], RefreshRotation | None]
PrincipalResolver = Callable[[Session, uuid.UUID], Principal | None]
# Resolve the authenticated caller's own identity for ``GET /me`` — app-wired to the
# store (e.g. ``IdentityService.current_user``) so auth never imports where users live
# (symmetric with the authenticate / tenant_resolver / revoke_sessions seams).
CurrentUserResolver = Callable[[Session, Principal], CurrentUser]
# Client-credentials seams (ADR 0088), app-wired to the service-account store. The
# machine analog of ``authenticate`` / ``token_version_resolver``: verify a client id +
# secret, and resolve that account's current token epoch. Wired together or not at all.
ClientAuthenticator = Callable[[Session, str, str], Principal | None]
ServiceTokenVersionResolver = Callable[[Session, Principal], int]


__all__ = [
    "Authenticator",
    "ClientAuthenticator",
    "CurrentUserResolver",
    "LoginTenantResolver",
    "PrincipalResolver",
    "RefreshIssuer",
    "RefreshRotator",
    "ServiceTokenVersionResolver",
    "TokenRevoker",
    "TokenVersionResolver",
]
