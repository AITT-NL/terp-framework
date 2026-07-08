"""Webhook tables: an owner-scoped subscription + an append-only delivery-attempt log.

``WebhookSubscription`` is a normal owner-scoped resource (``BaseTable`` + ``OwnedMixin``):
its creator owns it and only the owner may edit / delete it — the per-row write gate
(ADR 0029), enforced centrally by ``BaseService`` with zero module code. Its signing
``secret`` is stored here but is **never** serialized out of the API boundary: no ``*Read``
DTO carries it (the ``schemas_exclude_sensitive_fields`` rule plus a runtime test enforce
that), and the delivery job reads it server-side only to sign the outbound payload.

``WebhookDelivery`` records one delivery **attempt** — immutable once written, exactly like
:class:`~terp.capabilities.audit.AuditEvent` / :class:`~terp.capabilities.outbox.OutboxMessage`:
it composes :class:`~terp.core.UUIDPrimaryKeyMixin` rather than ``BaseTable`` (there is no
``updated_at`` and no optimistic-concurrency ``version`` — a delivery fact never changes),
and the ``WEBHOOK_DELIVER`` job appends one row per attempt. ``subscription_id`` is an
FK-less indexed UUID (like ``AuditEvent.actor_id``) so the delivery history survives a
subscription's deletion. Every caller-influenceable ``str`` column caps its length so a
hostile or oversized value can never break the INSERT.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Final

from sqlalchemy import DateTime
from sqlmodel import Field, SQLModel

from terp.core import BaseTable, OwnedMixin, UUIDPrimaryKeyMixin

# Terminal delivery outcomes (a plain str column, never a higher-layer enum — this leaf
# stays dependency-light, like ``AuditEvent.action`` / ``OutboxMessage.kind``).
OUTCOME_DELIVERED: Final[str] = "delivered"  # endpoint accepted (2xx)
OUTCOME_FAILED: Final[str] = "failed"  # non-2xx / network error (retried by the outbox)
OUTCOME_BLOCKED: Final[str] = "blocked"  # SSRF re-check denied the target at delivery time
OUTCOME_SKIPPED: Final[str] = "skipped"  # subscription removed / inactive by delivery time

# Hard caps so a hostile / oversized value can never break the INSERT or the trail.
_URL_MAX: Final[int] = 2048
# The stored `secret` holds the sealed-at-rest ciphertext (ADR 0076), not the raw input:
# the seal of the schema's 256-char maximum input is ~447 chars, so the column caps at 512.
_SECRET_MAX: Final[int] = 512
_EVENT_MAX: Final[int] = 128
_OUTCOME_MAX: Final[int] = 16
_ERROR_MAX: Final[int] = 2000


def _utc_now() -> datetime:
    """UTC ``now`` provider for this non-``BaseTable`` append-only row."""
    return datetime.now(UTC)


class WebhookSubscription(BaseTable, OwnedMixin, table=True):
    """An owner-scoped outbound-webhook registration: deliver *event* to *target_url*.

    ``id`` / ``created_at`` / ``updated_at`` / ``version`` are inherited from ``BaseTable``;
    ``owner_id`` from ``OwnedMixin`` (stamped from the request actor on create, then enforced
    as the per-row write gate). ``secret`` signs each delivery (HMAC-SHA256); it is stored
    **sealed at rest** (the service chokepoint seals it before persisting — ADR 0076) and is
    **never** serialized in a Read DTO.
    """

    __tablename__ = "webhook_subscription"

    target_url: str = Field(max_length=_URL_MAX, index=True)
    secret: str = Field(max_length=_SECRET_MAX)
    event: str = Field(max_length=_EVENT_MAX, index=True)
    active: bool = Field(default=True, index=True)


class WebhookDelivery(UUIDPrimaryKeyMixin, SQLModel, table=True):  # arch-allow-table-models-use-base-table: append-only delivery-attempt log (like AuditEvent) — immutable, no updated_at/version by design (see module docstring)
    __tablename__ = "webhook_delivery"

    subscription_id: uuid.UUID = Field(index=True)
    event: str = Field(max_length=_EVENT_MAX, index=True)
    outcome: str = Field(max_length=_OUTCOME_MAX, index=True)
    response_code: int | None = Field(default=None)
    attempt: int = Field(default=1)
    last_error: str | None = Field(default=None, max_length=_ERROR_MAX)
    created_at: datetime = Field(
        default_factory=_utc_now,
        sa_type=DateTime(timezone=True),  # type: ignore[call-overload]
        nullable=False,
        index=True,
    )


__all__ = [
    "OUTCOME_BLOCKED",
    "OUTCOME_DELIVERED",
    "OUTCOME_FAILED",
    "OUTCOME_SKIPPED",
    "WebhookDelivery",
    "WebhookSubscription",
]
