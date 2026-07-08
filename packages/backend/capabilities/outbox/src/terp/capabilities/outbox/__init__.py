"""terp.capabilities.outbox — durable, transactional, leased post-commit delivery.

The reliable delivery mechanism the dispatcher seam (ADR 0008) was designed for, and
the drop-in that makes the jobs seam (ADR 0043) survive a restart (ADR 0045). It owns
one append-only :class:`OutboxMessage` table and supplies:

* :class:`OutboxJobQueue` — a **durable** :class:`~terp.core.JobQueue` that records each
  enqueued job as an outbox row, atomically with the business write, instead of running
  it inline. Marked durable, so ``create_app(require_durable_jobs=True)`` accepts it.
* :func:`outbox_event_dispatcher` — a durable :data:`~terp.core.EventDispatcher` that
  records each emitted event as an outbox row on the producer's session.
* :class:`OutboxWorker` — the leased, retrying consumer (``terp jobs worker``) that
  claims due rows, runs jobs through the context-binding kernel runner and events
  through the in-process handlers, and retries / dead-letters per the
  :class:`~terp.core.RetryPolicy`.

Wiring is composition-root only, with **no** ``enqueue`` / ``emit`` call-site change::

    create_app(..., job_queue=OutboxJobQueue(), event_dispatcher=outbox_event_dispatcher,
               require_durable_jobs=settings.is_production)

It depends only on ``terp-core`` (and, for delivering events, the in-process eventbus
capability when one is installed); it never imports a broker engine — those are later,
separately-installed adapters (ADR 0045).
"""

from __future__ import annotations

from terp.capabilities.outbox.models import (
    KIND_EVENT,
    KIND_JOB,
    STATUS_DEAD_LETTERED,
    STATUS_DISPATCHED,
    STATUS_PENDING,
    OutboxMessage,
)
from terp.capabilities.outbox.queue import OutboxJobQueue, outbox_event_dispatcher
from terp.capabilities.outbox.worker import (
    DrainResult,
    OutboxWorker,
    deliver_event_in_process,
)

__all__ = [
    "KIND_EVENT",
    "KIND_JOB",
    "STATUS_DEAD_LETTERED",
    "STATUS_DISPATCHED",
    "STATUS_PENDING",
    "DrainResult",
    "OutboxJobQueue",
    "OutboxMessage",
    "OutboxWorker",
    "deliver_event_in_process",
    "outbox_event_dispatcher",
]
