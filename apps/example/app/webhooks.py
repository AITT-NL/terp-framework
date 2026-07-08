"""Example wiring: deliver webhooks when a note is created.

Subscribes the webhooks capability's generic fan-out to the catalog
:data:`~control_plane.events.NOTE_CREATED` event. The handler runs **synchronously inside
the note-create transaction** (the in-process dispatcher), so it obtains the producer's
session from the eventbus seam and enqueues a ``WEBHOOK_DELIVER`` job for each matching
active subscription **atomically with the note write** (no dual-write). The durable
``OutboxJobQueue`` then carries each delivery to ``terp jobs worker``, which signs and POSTs
it off-request — the external call never happens in this request.

Importing this module (from :mod:`app.main`) is what registers the subscription.
"""

from __future__ import annotations

from terp.core import EventEnvelope

from terp.capabilities.eventbus import current_event_session, subscribe
from terp.capabilities.webhooks import enqueue_webhook_deliveries

from control_plane.events import NOTE_CREATED


@subscribe(NOTE_CREATED)
def deliver_webhooks_on_note_created(envelope: EventEnvelope) -> None:
    """Fan a created note out to every active webhook subscription for the event."""
    enqueue_webhook_deliveries(current_event_session(), envelope)


__all__ = ["deliver_webhooks_on_note_created"]
