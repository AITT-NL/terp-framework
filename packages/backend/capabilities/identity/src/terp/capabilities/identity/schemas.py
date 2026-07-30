"""Identity DTOs. ``UserRead`` never exposes ``hashed_password``."""

from __future__ import annotations

import datetime
import uuid

from sqlmodel import Field

from terp.core import BaseSchema, BaseUpdateSchema


class UserRead(BaseSchema):
    id: uuid.UUID
    email: str
    role: int
    is_active: bool
    version: int
    created_at: datetime.datetime
    updated_at: datetime.datetime


class ServiceAccountCreate(BaseSchema):
    """What an operator supplies to provision a machine credential (ADR 0088).

    Neither the client id nor the secret is an input: both are generated, so a
    machine credential can never be provisioned with a guessable value somebody
    typed. ``role_rank`` is required rather than defaulted — the whole point of the
    feature is that the authority an integration gets is a deliberate decision.
    """

    name: str = Field(max_length=128)
    role_rank: int
    description: str | None = Field(default=None, max_length=512)
    expires_at: datetime.datetime | None = None


class ServiceAccountUpdate(BaseUpdateSchema):
    """The mutable face of a machine credential. The secret is not among it.

    Rotating a secret is a re-provision, not an edit: there is no field here that
    could quietly replace the credential without the operator being handed the new
    one.
    """

    name: str | None = Field(default=None, max_length=128)
    description: str | None = Field(default=None, max_length=512)
    role_rank: int | None = None
    is_active: bool | None = None
    expires_at: datetime.datetime | None = None


class ServiceAccountRead(BaseSchema):
    """A machine credential as it is safe to show. ``hashed_secret`` is never on it."""

    id: uuid.UUID
    name: str
    description: str | None
    client_id: str
    role: int
    is_active: bool
    version: int
    expires_at: datetime.datetime | None
    last_used_at: datetime.datetime | None
    created_at: datetime.datetime
    updated_at: datetime.datetime
