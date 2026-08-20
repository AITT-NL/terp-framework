"""Auth request/response DTOs."""

from __future__ import annotations

import uuid

from sqlmodel import Field

from terp.core import BaseSchema


class LoginRequest(BaseSchema):
    email: str = Field(max_length=320)
    password: str = Field(max_length=256)


class ClientCredentialsRequest(BaseSchema):
    """A machine integration's credential pair — the ``POST /token`` body (ADR 0088).

    The non-interactive analog of :class:`LoginRequest`. Both fields are generated,
    high-entropy strings; the caps are generous enough for a rotated-format secret and
    still bound the input.
    """

    client_id: str = Field(max_length=128)
    client_secret: str = Field(max_length=512)


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
    permissions: tuple[str, ...] = ()
    """The caller's effective permission names, for the UI to gate on (ADR 0096).

    Rank alone was not enough to hide what the server would refuse. A screen whose write
    needs a *named* grant (``definitions.publish``) could only compare rank, so it hid by a
    proxy and handled the 403 anyway — showing a button it knew might fail, or hiding one
    the user was entitled to. This is the same set the guard enforces, projected for
    display, so a UI can hide exactly what would be refused.

    Empty for an app that mounts no grant capability (there are no named permissions to
    hold), which is why it defaults rather than being required. It is a *display* input,
    never an authorization decision: the server re-checks every request, and a client that
    trusts this list has moved the gate to the wrong side of the wire.
    """


__all__ = ["AccessToken", "ClientCredentialsRequest", "CurrentUser", "LoginRequest"]
