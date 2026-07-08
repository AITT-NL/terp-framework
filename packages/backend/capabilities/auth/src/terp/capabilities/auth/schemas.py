"""Auth request/response DTOs."""

from __future__ import annotations

import uuid

from sqlmodel import Field

from terp.core import BaseSchema


class LoginRequest(BaseSchema):
    email: str = Field(max_length=320)
    password: str = Field(max_length=256)


class AccessToken(BaseSchema):
    access_token: str  # arch-allow-schemas-exclude-sensitive-fields: the bearer token the login endpoint exists to mint
    token_type: str = "bearer"


class CurrentUser(BaseSchema):
    """The authenticated caller's own identity — the ``/me`` (who-am-I) response.

    The frontend's session contract pairs this with :class:`AccessToken`. It is the
    server-validated current identity (resolved through the wired principal provider —
    the revocable one in the bundled stack), so it reflects the live store, not just the
    token's claims. The caller's role is on the wire as both the numeric ``role_rank``
    (the comparable primitive, ADR 0004 / 0022) and a human-readable ``role_name``.
    """

    id: uuid.UUID
    email: str
    role_rank: int
    role_name: str


__all__ = ["AccessToken", "CurrentUser", "LoginRequest"]
