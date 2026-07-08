"""Webhook DTOs.

The signing ``secret`` is **write-only**: a client supplies it on create / update (an input
body — the ``schemas_exclude_sensitive_fields`` rule deliberately exempts inputs), but **no
Read DTO ever serializes it** (ADR 0020 + that same rule, plus a runtime test). The delivery
log is append-only, so it has only a Read DTO — there is no delivery write surface.
"""

from __future__ import annotations

import datetime
import uuid

from sqlmodel import Field

from terp.core import BaseSchema, BaseUpdateSchema

# Mirror the model caps so an oversized value is rejected at the boundary (a DoS cap), and
# require a non-trivial signing secret so a webhook is never signed with a guessable key.
_URL_MAX = 2048
_SECRET_MIN = 16
_SECRET_MAX = 256
_EVENT_MAX = 128


class WebhookSubscriptionCreate(BaseSchema):
    """Register a webhook. ``secret`` is supplied here (input only) and never returned."""

    target_url: str = Field(max_length=_URL_MAX)
    secret: str = Field(min_length=_SECRET_MIN, max_length=_SECRET_MAX)
    event: str = Field(max_length=_EVENT_MAX)
    active: bool = True


class WebhookSubscriptionUpdate(BaseUpdateSchema):
    """Patch a webhook (optimistic concurrency via the inherited required ``version``)."""

    target_url: str | None = Field(default=None, max_length=_URL_MAX)
    secret: str | None = Field(default=None, min_length=_SECRET_MIN, max_length=_SECRET_MAX)
    event: str | None = Field(default=None, max_length=_EVENT_MAX)
    active: bool | None = None
    # `version: int` is inherited from BaseUpdateSchema and required (optimistic concurrency).


class WebhookSubscriptionRead(BaseSchema):
    """The subscription as returned by the API — deliberately **without** ``secret``."""

    id: uuid.UUID
    target_url: str
    event: str
    active: bool
    owner_id: uuid.UUID | None
    version: int
    created_at: datetime.datetime
    updated_at: datetime.datetime


class WebhookDeliveryRead(BaseSchema):
    """One immutable delivery attempt, as returned by the read-only delivery log."""

    id: uuid.UUID
    subscription_id: uuid.UUID
    event: str
    outcome: str
    response_code: int | None
    attempt: int
    last_error: str | None
    created_at: datetime.datetime


__all__ = [
    "WebhookDeliveryRead",
    "WebhookSubscriptionCreate",
    "WebhookSubscriptionRead",
    "WebhookSubscriptionUpdate",
]
