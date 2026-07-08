"""The durable producers: a job queue and an event dispatcher that persist an outbox row.

These are the drop-in backends a composition root wires to make post-commit delivery
survive a restart — with **no** change to any ``enqueue`` / ``emit`` call site (ADR
0008's promise)::

    create_app(..., job_queue=OutboxJobQueue(), event_dispatcher=outbox_event_dispatcher,
               require_durable_jobs=settings.is_production)

:meth:`OutboxJobQueue.enqueue` and :func:`outbox_event_dispatcher` both append an
:class:`~terp.capabilities.outbox.models.OutboxMessage` on the **session they already
receive** — the business write's session — so the row commits in the same transaction
as the mutation that produced it (no dual-write). The job queue marks itself durable
(:func:`~terp.core.mark_durable_job_queue`), so ``create_app(require_durable_jobs=True)``
accepts it where the in-process default is refused.
"""

from __future__ import annotations

from sqlmodel import Session

from terp.core import (
    EventDefinition,
    EventEnvelope,
    JobEnvelope,
    JobQueue,
    mark_durable_job_queue,
)

from terp.capabilities.outbox._serde import (
    event_envelope_to_payload,
    job_envelope_to_payload,
)
from terp.capabilities.outbox.models import KIND_EVENT, KIND_JOB, OutboxMessage
from terp.capabilities.outbox.store import append


class OutboxJobQueue(JobQueue):
    """A durable :class:`~terp.core.JobQueue` that records each job as an outbox row.

    Unlike :class:`~terp.core.InProcessJobQueue` (which runs the handler inline), this
    only *records* the envelope — atomically with the business write on the caller's
    session — for a leased :class:`~terp.capabilities.outbox.OutboxWorker` to drain
    off-request, surviving a restart. It marks itself durable, so
    ``create_app(require_durable_jobs=True)`` accepts it.
    """

    def __init__(self) -> None:
        mark_durable_job_queue(self)

    def enqueue(self, session: Session, envelope: JobEnvelope) -> str:
        """Persist *envelope* as a ``pending`` outbox row on *session*; return its id."""
        message = OutboxMessage(
            kind=KIND_JOB,
            name=envelope.name,
            payload=job_envelope_to_payload(envelope),
            idempotency_key=envelope.idempotency_key,
        )
        append(session, message)
        return str(message.id)


def outbox_event_dispatcher(
    session: Session, envelope: EventEnvelope, definition: EventDefinition
) -> None:
    """A durable :data:`~terp.core.EventDispatcher`: record each event as an outbox row.

    Installed at ``create_app(event_dispatcher=outbox_event_dispatcher)``. It records
    the envelope on the producer's session — atomic with the business write — for the
    :class:`~terp.capabilities.outbox.OutboxWorker` to deliver to in-process handlers
    off-request. *definition* satisfies the dispatcher seam contract; the stored
    envelope already carries the canonical name / visibility / payload.
    """
    message = OutboxMessage(
        kind=KIND_EVENT,
        name=envelope.name,
        payload=event_envelope_to_payload(envelope),
    )
    append(session, message)


__all__ = ["OutboxJobQueue", "outbox_event_dispatcher"]
