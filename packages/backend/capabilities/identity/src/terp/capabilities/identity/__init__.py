"""terp.capabilities.identity — the persisted user store + authentication backing.

Provides a ``User`` model, an ``IdentityService`` (CRUD + ``authenticate``), and
the DTOs the login flow needs. It backs the auth capability's login flow (the app
wires ``IdentityService().authenticate`` as the authenticator) and is the store
that the ``terp-cap-users`` capability administers.

This is a **library** capability: it ships no router (user administration lives in
``terp-cap-users``), so it is imported directly rather than discovered.
"""

from __future__ import annotations

from terp.capabilities.identity.federated import (
    FederatedIdentityLink,
    FederatedIdentityService,
    FederatedIdentityUpdate,
)
from terp.capabilities.identity.models import FederatedIdentity, RefreshToken, User
from terp.capabilities.identity.refresh import RefreshTokenService
from terp.capabilities.identity.schemas import UserRead
from terp.capabilities.identity.service import IdentityService

__all__ = [
    "FederatedIdentity",
    "FederatedIdentityLink",
    "FederatedIdentityService",
    "FederatedIdentityUpdate",
    "IdentityService",
    "RefreshToken",
    "RefreshTokenService",
    "User",
    "UserRead",
]
