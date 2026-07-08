"""The webhook trigger: fan a domain event out to its matching webhook subscriptions.

An app wires this to a catalog event with the eventbus ``@subscribe`` decorator. When the
event fires — synchronously, **inside the business write's transaction** — this enqueues one
``WEBHOOK_DELIVER`` job per active subscription registered for that event **on the producer's
session**, so each durable outbox row commits atomically with the business write (no
dual-write). The outbox worker then delivers each off-request. The external HTTP call is in
the job handler, never here — this only stages durable work.

The function takes the session **explicitly** (rather than reading ambient state), so this
capability stays decoupled from the event bus; the thin app glue obtains the producer's
session from the eventbus seam (``current_event_session()``) and passes it in.
"""

from __future__ import annotations

import uuid

from sqlmodel import Session

from terp.core import EventEnvelope, enqueue

from terp.capabilities.webhooks.delivery import WEBHOOK_DELIVER, WebhookDeliveryPayload
from terp.capabilities.webhooks.service import WebhookSubscriptionService

_service = WebhookSubscriptionService()


def enqueue_webhook_deliveries(session: Session, envelope: EventEnvelope) -> int:
    """Enqueue a ``WEBHOOK_DELIVER`` job for each active subscription matching *envelope*.

    Pass the **producer's** *session* (e.g. ``enqueue_webhook_deliveries(current_event_session(),
    envelope)`` from an event handler), so every enqueued delivery row commits atomically with
    the business write. Each job carries a fresh ``delivery_id`` (used as the idempotency key)
    so a redelivered job re-sends the same identifiable delivery. Returns the number enqueued.
    """
    subscriptions = _service.active_for_event(session, envelope.name)
    for subscription in subscriptions:
        delivery_id = uuid.uuid4()
        enqueue(
            session,
            job=WEBHOOK_DELIVER,
            payload=WebhookDeliveryPayload(
                subscription_id=subscription.id,
                delivery_id=delivery_id,
                event=envelope.name,
                data=dict(envelope.payload),
            ),
            idempotency_key=str(delivery_id),
        )
    return len(subscriptions)


__all__ = ["enqueue_webhook_deliveries"]
