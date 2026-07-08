"""The Celery producer: a durable :class:`~terp.core.JobQueue` backed by a Celery broker.

:meth:`CeleryJobQueue.enqueue` ships the :class:`~terp.core.JobEnvelope` as the JSON
``kwargs`` of one canonical Terp task (:data:`TERP_JOB_TASK`), routed to the
:class:`~terp.core.JobDefinition`'s ``queue`` hint. A Celery worker (see
:func:`~terp.capabilities.jobs_celery.worker.register_terp_worker`) resolves the Terp
handler **by name** through the kernel runner and re-binds the originating actor / tenant /
request id (the jobs design's §7) — so the *same* catalog handler runs under Celery with
zero domain change from the in-process default.

It marks itself **durable** (:func:`~terp.core.mark_durable_job_queue`): a real broker
(Redis / RabbitMQ with persistence) holds the message across an app restart, so
``create_app(require_durable_jobs=True)`` accepts it where the in-process default is
refused.

**Transactionality caveat.** ``send_task`` publishes to the broker *immediately*, **not**
on the caller's DB transaction — so a job enqueued inside a business write is delivered
even if that write later rolls back (a dual-write hazard). For transactional capture
exactly-with-the-commit, wire :class:`~terp.capabilities.outbox.OutboxJobQueue` as the
``JobQueue`` and relay outbox rows to Celery; this direct adapter is the simplest path for
jobs that tolerate at-least-once delivery plus that post-enqueue-rollback edge (the
design's §10 / §17).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from sqlmodel import Session

from terp.core import JobEnvelope, JobQueue, mark_durable_job_queue
from terp.core.jobs import active_job_catalog

from terp.capabilities.jobs_celery._serde import job_envelope_to_kwargs

if TYPE_CHECKING:  # pragma: no cover - typing only; the engine is wired at the composition root
    from celery import Celery  # arch-allow-no-adhoc-background-runtime: this capability IS the Celery JobQueue adapter — the one governed place the engine is imported, behind the jobs seam

# The single canonical Terp task a Celery worker registers (see register_terp_worker) and
# the producer sends to. ONE generic task — not one Celery task per job — keeps the Celery
# registry from drifting against the JobCatalog: the handler is always resolved by envelope
# name through the kernel runner, so the catalog stays the single source of truth.
TERP_JOB_TASK: Final[str] = "terp.jobs.run"


class CeleryJobQueue(JobQueue):
    """A durable :class:`~terp.core.JobQueue` that dispatches each job to a Celery broker."""

    def __init__(self, celery_app: Celery, *, task_name: str = TERP_JOB_TASK) -> None:
        self._app = celery_app
        self._task_name = task_name
        mark_durable_job_queue(self)

    def enqueue(self, session: Session, envelope: JobEnvelope) -> str:
        """Send *envelope* to the broker as the canonical Terp task; return the Celery id.

        The routing queue is the :class:`~terp.core.JobDefinition`'s ``queue`` hint resolved
        from the *active* catalog (so a job's queue travels with its definition); an envelope
        whose job a deploy has since removed falls back to the ``"default"`` queue, and the
        worker's :func:`~terp.core._internal.job_runtime.run_job` rejects it fail-closed.
        *session* is unused — Celery delivers over its broker, not the caller's transaction
        (see the module docstring's transactionality caveat).
        """
        definition = active_job_catalog().get(envelope.name)
        queue = definition.queue if definition is not None else "default"
        result = self._app.send_task(
            self._task_name,
            kwargs={"envelope": job_envelope_to_kwargs(envelope)},
            queue=queue,
        )
        return str(result.id)


__all__ = ["TERP_JOB_TASK", "CeleryJobQueue"]
