"""terp.capabilities.identity — the persisted user store + authentication backing.

Provides a ``User`` model, an ``IdentityService`` (CRUD + ``authenticate``), and
the DTOs the login flow needs. It backs the auth capability's login flow (the app
wires ``IdentityService().authenticate`` as the authenticator) and is the store
that the ``terp-cap-users`` capability administers.

It also owns the **non-human** subject: ``ServiceAccount`` +
``ServiceAccountService`` back the client-credentials grant (ADR 0088), so a
machine integration authenticates as itself instead of borrowing an operator's
login — and is authorized and revoked through exactly the same machinery.

This is a **library** capability: it ships no router (user administration lives in
``terp-cap-users``), so it is imported directly rather than discovered.
"""

from __future__ import annotations

from terp.capabilities.identity.federated import (
    FederatedIdentityLink,
    FederatedIdentityService,
    FederatedIdentityUpdate,
)
from terp.capabilities.identity.models import (
    FederatedIdentity,
    RefreshToken,
    ServiceAccount,
    User,
)
from terp.capabilities.identity.refresh import RefreshTokenService
from terp.capabilities.identity.schemas import UserRead
from terp.capabilities.identity.service import IdentityService
from terp.capabilities.identity.service_accounts import ServiceAccountService

__all__ = [
    "FederatedIdentity",
    "FederatedIdentityLink",
    "FederatedIdentityService",
    "FederatedIdentityUpdate",
    "IdentityService",
    "RefreshToken",
    "RefreshTokenService",
    "ServiceAccount",
    "ServiceAccountService",
    "User",
    "UserRead",
]
