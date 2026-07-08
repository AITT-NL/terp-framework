"""terp.capabilities.webhooks — reliable, signed, SSRF-guarded outbound webhooks.

Built **only** on the shipped ports: the jobs seam (:func:`terp.core.enqueue` + a typed
:class:`~terp.core.JobDefinition`) and the durable outbox (for retry / dead-letter). It adds
no engine and changes no ``terp.core``.

* A consumer registers an owner-scoped :class:`WebhookSubscription` through the discovered,
  admin-only router at ``/api/v1/webhooks``; the signing ``secret`` is supplied on create and
  is never serialized back out.
* An app wires :func:`enqueue_webhook_deliveries` to a catalog event with the eventbus
  ``@subscribe`` decorator, so when the event fires the matching deliveries are enqueued **on
  the producer's session** — atomically with the business write (no dual-write).
* The :data:`WEBHOOK_DELIVER` job (drained by the outbox worker, ``terp jobs worker``) signs
  the payload (HMAC-SHA256), re-checks the target against the SSRF denylist, POSTs with a
  strict timeout and no redirect following, records a :class:`WebhookDelivery`, and lets a
  failure propagate so the outbox retries with backoff and dead-letters.

It depends only on ``terp-core`` and ``httpx`` — never a sibling capability or a broker
engine; the app composes the durable ``OutboxJobQueue`` at ``create_app``.
"""

from __future__ import annotations

from terp.capabilities.webhooks.delivery import (
    WEBHOOK_DELIVER,
    WebhookDeliveryError,
    WebhookDeliveryPayload,
    WebhookResponse,
    WebhookSender,
    active_webhook_sender,
    deliver_webhook,
    reset_webhook_sender,
    set_webhook_sender,
)
from terp.capabilities.webhooks.models import (
    OUTCOME_BLOCKED,
    OUTCOME_DELIVERED,
    OUTCOME_FAILED,
    OUTCOME_SKIPPED,
    WebhookDelivery,
    WebhookSubscription,
)
from terp.capabilities.webhooks.router import module, router
from terp.capabilities.webhooks.sealing import (
    WebhookSecretError,
    is_sealed_secret,
    seal_secret,
    unseal_secret,
)
from terp.capabilities.webhooks.schemas import (
    WebhookDeliveryRead,
    WebhookSubscriptionCreate,
    WebhookSubscriptionRead,
    WebhookSubscriptionUpdate,
)
from terp.capabilities.webhooks.service import WebhookSubscriptionService, list_deliveries
from terp.capabilities.webhooks.ssrf import (
    CLOUD_METADATA_ADDRESS,
    PinnedTarget,
    WebhookTargetError,
    is_denied_address,
    resolve_pinned_target,
    validate_webhook_target,
)
from terp.capabilities.webhooks.store import record_delivery
from terp.capabilities.webhooks.triggers import enqueue_webhook_deliveries

__all__ = [
    "CLOUD_METADATA_ADDRESS",
    "OUTCOME_BLOCKED",
    "OUTCOME_DELIVERED",
    "OUTCOME_FAILED",
    "OUTCOME_SKIPPED",
    "WEBHOOK_DELIVER",
    "PinnedTarget",
    "WebhookDelivery",
    "WebhookDeliveryError",
    "WebhookDeliveryPayload",
    "WebhookDeliveryRead",
    "WebhookResponse",
    "WebhookSecretError",
    "WebhookSender",
    "WebhookSubscription",
    "WebhookSubscriptionCreate",
    "WebhookSubscriptionRead",
    "WebhookSubscriptionService",
    "WebhookSubscriptionUpdate",
    "WebhookTargetError",
    "active_webhook_sender",
    "deliver_webhook",
    "enqueue_webhook_deliveries",
    "is_denied_address",
    "is_sealed_secret",
    "list_deliveries",
    "module",
    "record_delivery",
    "reset_webhook_sender",
    "resolve_pinned_target",
    "router",
    "seal_secret",
    "set_webhook_sender",
    "unseal_secret",
    "validate_webhook_target",
]
