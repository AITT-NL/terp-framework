"""terp.capabilities.jobs_celery — run catalog jobs on a Celery broker (the first engine adapter).

The first proof that Terp's jobs seam (ADR 0043) is genuinely engine-agnostic: a thin
:class:`~terp.core.JobQueue` adapter over Celery. Wiring is composition-root only, with
**no** ``enqueue`` call-site change — the *same* catalog job + handler that runs inline
under :class:`~terp.core.InProcessJobQueue` runs on a Celery worker here::

    # producer / web process
    create_app(..., job_queue=CeleryJobQueue(celery_app),
               require_durable_jobs=settings.is_production)

    # worker process
    register_terp_worker(celery_app)        # then: celery -A your.celery_app worker

:meth:`CeleryJobQueue.enqueue` ships the :class:`~terp.core.JobEnvelope` to a single
canonical Terp task; the worker rebuilds it and runs it through the kernel's
context-binding :func:`~terp.core._internal.job_runtime.run_job`, re-binding the
originating ``actor_id`` / ``tenant_id`` / ``request_id`` (the jobs design's §7) so every
write a job makes stays audited + actor / tenant stamped. The job's
:class:`~terp.core.RetryPolicy` maps onto Celery's own retry, so the retry budget travels
with the :class:`~terp.core.JobDefinition` rather than being re-specified per broker.

It depends only on ``terp-core`` + ``celery`` and imports the engine **solely** behind the
jobs seam — the ``no_adhoc_background_runtime`` rule keeps Celery out of app code, and this
adapter is the one governed place it is allowed.
"""

from __future__ import annotations

from terp.capabilities.jobs_celery.queue import TERP_JOB_TASK, CeleryJobQueue
from terp.capabilities.jobs_celery.worker import register_terp_worker

__all__ = ["TERP_JOB_TASK", "CeleryJobQueue", "register_terp_worker"]
