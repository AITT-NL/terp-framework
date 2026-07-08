"""The Celery consumer: register the canonical Terp task that runs a job in a worker.

:func:`register_terp_worker` wires one task (:data:`~terp.capabilities.jobs_celery.queue.TERP_JOB_TASK`)
onto a Celery app. A Celery worker invokes it for each enqueued job: it rebuilds the
:class:`~terp.core.JobEnvelope` from the JSON ``kwargs`` and runs it through the kernel's
context-binding :func:`~terp.core._internal.job_runtime.run_job` — re-binding the
envelope's actor / tenant / request id (the jobs design's §7), so every write the job makes
stays audited + actor / tenant stamped, with the configured **system actor** standing in
when no user originated the work. The *same* catalog handler therefore runs under Celery
exactly as under the in-process default — the engine swap touches no domain code.

On failure the task maps the job's :class:`~terp.core.RetryPolicy` onto Celery's own retry:
it reschedules with the policy's exponential backoff until ``max_attempts`` is reached, then
lets the exception propagate (Celery routes it to its dead-letter / error handling). So a
job's retry budget travels with its :class:`~terp.core.JobDefinition` across the engine
boundary rather than being re-specified per broker.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from sqlmodel import Session

from terp.core import RetryPolicy
from terp.core.jobs import active_job_catalog

# run_job is the kernel's context-binding executor, kept _internal so an app module reaches
# background work solely through the typed enqueue chokepoint; the engine adapter is the
# legitimate consumer half of the jobs seam that drives it (mirrors the outbox worker).
from terp.core._internal.job_runtime import run_job  # arch-allow-no-internal-imports: the engine adapter is the consumer half of the jobs seam; run_job is the kernel's context-binding executor, kept _internal so app modules cannot run jobs directly

from terp.capabilities.jobs_celery._serde import kwargs_to_job_envelope
from terp.capabilities.jobs_celery.queue import TERP_JOB_TASK

if TYPE_CHECKING:  # pragma: no cover - typing only; the engine is wired at the composition root
    from celery import Celery  # arch-allow-no-adhoc-background-runtime: this capability IS the Celery JobQueue adapter — the one governed place the engine is imported, behind the jobs seam


def _retry_countdown(attempt: int, retry: RetryPolicy) -> float:
    """Exponential backoff (seconds) before retrying the failed *attempt*, capped by policy."""
    delay = retry.backoff_seconds * (retry.backoff_multiplier ** (attempt - 1))
    return min(delay, retry.max_backoff_seconds)


def _retry_for(name: str, default: RetryPolicy) -> RetryPolicy:
    """The retry budget governing job *name*: its catalog policy, or *default* if unknown."""
    job = active_job_catalog().get(name)
    return job.retry if job is not None else default


@dataclass(frozen=True)
class _RetryDirective:
    """A request to reschedule a failed job via Celery (the engine-coupled retry call)."""

    exc: BaseException
    countdown: float
    max_retries: int


def _execute_envelope(
    envelope: Any,
    *,
    attempt: int,
    job_session_factory: Callable[[], Session] | None,
    default_retry: RetryPolicy,
) -> _RetryDirective | None:
    """Run one job envelope; signal what should happen next (the testable worker core).

    Rebuilds the envelope (stamping *attempt*), runs it through :func:`run_job`, and:
    returns ``None`` on success; **re-raises** the handler's exception once the job's retry
    budget is spent (``attempt`` reached ``max_attempts`` — Celery then routes it to its
    error handling); otherwise returns a :class:`_RetryDirective` the thin task body turns
    into ``self.retry(...)``. Splitting the decision out keeps the engine-coupled retry call
    a one-liner and the policy logic unit-testable without a broker.
    """
    job_envelope = replace(kwargs_to_job_envelope(envelope), attempt=attempt)
    try:
        run_job(job_envelope, session_factory=job_session_factory)
    except Exception as exc:  # noqa: BLE001 - any handler failure becomes a retry / terminal raise
        policy = _retry_for(job_envelope.name, default_retry)
        if attempt >= policy.max_attempts:
            raise
        return _RetryDirective(
            exc=exc,
            countdown=_retry_countdown(attempt, policy),
            max_retries=policy.max_attempts - 1,
        )
    return None


def register_terp_worker(
    celery_app: Celery,
    *,
    task_name: str = TERP_JOB_TASK,
    job_session_factory: Callable[[], Session] | None = None,
    retry: RetryPolicy | None = None,
) -> Any:
    """Register the canonical Terp job task on *celery_app* and return it.

    The worker-side counterpart of :class:`~terp.capabilities.jobs_celery.CeleryJobQueue`:
    a single bound task a Celery worker runs for every enqueued job. It stamps the attempt
    from Celery's own retry count and executes through :func:`_execute_envelope` (the §7
    context binding); a handler failure reschedules via Celery using the job's
    :class:`~terp.core.RetryPolicy` backoff until its ``max_attempts``, then propagates.
    *job_session_factory* is passed to :func:`run_job` for each job's own audited unit
    (tests inject a synthetic engine); *retry* is the fallback budget for a job missing
    from the catalog.
    """
    default_retry = retry or RetryPolicy()

    @celery_app.task(name=task_name, bind=True)
    def _run_terp_job(self: Any, envelope: dict[str, Any]) -> None:
        directive = _execute_envelope(
            envelope,
            attempt=self.request.retries + 1,
            job_session_factory=job_session_factory,
            default_retry=default_retry,
        )
        if directive is not None:
            raise self.retry(  # pragma: no cover - engine-coupled reschedule (exercised against a broker)
                exc=directive.exc,
                countdown=directive.countdown,
                max_retries=directive.max_retries,
            )

    return _run_terp_job


__all__ = ["register_terp_worker"]
