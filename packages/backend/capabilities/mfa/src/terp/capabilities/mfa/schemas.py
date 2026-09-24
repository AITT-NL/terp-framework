"""MFA DTOs.

``MfaEnrolmentCreate`` is **server-built only**: the service generates the secret and
seals it before constructing this, so a client never supplies either. ``MfaEnrolmentRead``
carries no secret at all — not sealed, not masked, not present. The one moment a
plaintext secret crosses the boundary is :class:`MfaSecretIssued`, returned exactly once
from the enrolment call, because an authenticator app cannot be enrolled without it.

``MfaSecretIssued`` is deliberately not a read DTO of the row. It is the response to one
action, and it exists as its own type so nothing can be tempted to return it from a
listing later.
"""

from __future__ import annotations

import datetime
import uuid

from sqlmodel import Field

from terp.core import BaseSchema, BaseUpdateSchema

from terp.capabilities.mfa.models import SECRET_MAX

_CODE_MAX = 32


class MfaEnrolmentCreate(BaseSchema):
    """The enrolment row — constructed by the service, never posted by a client."""

    user_id: uuid.UUID
    secret: str = Field(min_length=1, max_length=SECRET_MAX)


class MfaEnrolmentUpdate(BaseUpdateSchema):
    """Patch the enrolment's live-ness (OCC via the inherited required ``version``).

    Only ``confirmed_at`` is patchable, and only the service sets it. The secret is
    append-only: replacing a factor means disabling it and enrolling again, which is two
    audited acts rather than one silent one.
    """

    confirmed_at: datetime.datetime | None = None
    last_used_step: int | None = None


class MfaEnrolmentRead(BaseSchema):
    """What a caller may learn about their own enrolment: that it exists, and whether it is live."""

    id: uuid.UUID
    user_id: uuid.UUID
    confirmed_at: datetime.datetime | None
    version: int
    created_at: datetime.datetime
    updated_at: datetime.datetime


class MfaSecretIssued(BaseSchema):
    """The one-time response to starting an enrolment: the secret, its URI, the codes."""

    # arch-allow-schemas-exclude-sensitive-fields: an authenticator app cannot be enrolled without the shared secret, so this one response must carry it. It is returned exactly once, at the moment it is generated, never read back from the row (which holds it sealed), and carried by no other DTO -- MfaEnrolmentRead has no secret field at all.
    secret: str
    provisioning_uri: str
    recovery_codes: list[str]


class MfaCodeRequest(BaseSchema):
    """A submitted code — a TOTP digit string or a recovery code."""

    code: str = Field(min_length=1, max_length=_CODE_MAX)


class MfaStatusRead(BaseSchema):
    """Whether the caller has a live second factor, and how many recovery codes remain."""

    enrolled: bool
    confirmed: bool
    recovery_codes_remaining: int


__all__ = [
    "MfaCodeRequest",
    "MfaEnrolmentCreate",
    "MfaEnrolmentRead",
    "MfaEnrolmentUpdate",
    "MfaSecretIssued",
    "MfaStatusRead",
]
