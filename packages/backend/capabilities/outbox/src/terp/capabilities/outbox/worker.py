"""The leased, retrying outbox worker — the consumer that drains pending rows.

``terp jobs worker`` (or a worker-container entrypoint) runs this loop. Each cycle it
**claims** a batch of due rows with a lease (so N workers drain one outbox without
double-dispatch), **executes** each — a job through the context-binding
:func:`~terp.core._internal.job_runtime.run_job` (so its writes stay audited +
actor / tenant stamped, the jobs design's §7), an event through the in-process
handlers — and records the outcome: ``dispatched`` on success, a **retry** with
exponential backoff, or ``dead_lettered`` once the job's
:class:`~terp.core.RetryPolicy` ``max_attempts`` is exhausted.

Delivery is **at-least-once**: a worker that crashes mid-flight loses its lease at
``locked_until``, and another reclaims and re-runs the row — so a handler must be
idempotent (its ``idempotency_key`` + the business unique keys). To stay correct on
SQLite (where a held read transaction blocks a writer on another connection), the
worker **claims a batch and detaches it**, then executes and finalizes each row in its
own short transaction — so a long-running job never keeps the bookkeeping connection's
lock open, and each job runs in its **own** audited unit opened by ``run_job``.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlmodel import Session

from terp.core import EventEnvelope, RetryPolicy
from terp.core.jobs import active_job_catalog

# run_job is the kernel's context-binding executor; only a JobQueue / the durable
# worker drives it (it stays _internal so an app module reaches background work solely
# through the typed enqueue chokepoint, never by running a job directly).
from terp.core._internal.job_runtime import run_job  # arch-allow-no-internal-imports: the durable worker is the consumer half of the jobs seam; run_job is the kernel's context-binding executor, kept _internal so app modules cannot run jobs directly

from terp.capabilities.outbox._serde import (
    payload_to_event_envelope,
    payload_to_job_envelope,
)
from terp.capabilities.outbox.models import (
    KIND_JOB,
    STATUS_DEAD_LETTERED,
    STATUS_DISPATCHED,
    STATUS_PENDING,
    OutboxMessage,
)
from terp.capabilities.outbox.store import claim_due, finalize

_ERROR_MAX = 2000

# Outcome of a finalize whose lease was lost mid-execution: the job outran its lease and
# another worker reclaimed + finalized the row, so this (stale) worker discards its result
# rather than clobbering the new owner. Re-delivery already happened (at-least-once); this
# only protects the bookkeeping. Distinct from every STATUS_* value.
_LOST = "lost"


def _utc_now() -> datetime:
    """UTC ``now`` provider (the worker's default clock; injectable for tests)."""
    return datetime.now(UTC)


def _clip(value: str) -> str:
    """Strip NUL bytes and clamp an error message to the ``last_error`` column bound."""
    return value.replace("\x00", "")[:_ERROR_MAX]


def _backoff_seconds(attempts: int, retry: RetryPolicy) -> float:
    """Exponential backoff for the *attempts*-th failure, capped at the policy max."""
    delay = retry.backoff_seconds * (retry.backoff_multiplier ** (attempts - 1))
    return min(delay, retry.max_backoff_seconds)


def deliver_event_in_process(envelope: EventEnvelope) -> None:
    """Deliver *envelope* to every in-process handler subscribed to its event.

    The worker's default terminal delivery for a ``kind="event"`` row: it fans the
    event out to the eventbus capability's handlers (the **real** in-process dispatch,
    never the active dispatcher — which is the outbox itself). An event with no
    subscribers is a no-op success. If the eventbus capability is not installed the
    import fails and the row retries / dead-letters — you should not produce events
    without a consumer.
    """
    from terp.capabilities.eventbus.registry import handlers_for

    for handler in handlers_for(envelope.name):
        handler(envelope)


@dataclass(frozen=True)
class _Claimed:
    """A detached snapshot of one claimed row: enough to execute and finalize it.

    Captured before the claim session closes, so the long-running execution never
    holds the bookkeeping connection's transaction open (SQLite-safe). Carries the
    cycle's *claim_id* so finalize can verify this worker still holds the lease.
    """

    id: uuid.UUID
    kind: str
    name: str
    payload: Mapping[str, Any]
    attempts: int
    claim_id: str


@dataclass(frozen=True)
class DrainResult:
    """The tally of one or more drain cycles (for the CLI loop and tests)."""

    claimed: int = 0
    dispatched: int = 0
    retried: int = 0
    dead_lettered: int = 0
    lost: int = 0


class OutboxWorker:
    """Claim, execute, and finalize due outbox rows; retry with backoff; dead-letter.

    Construct it with a *session_factory* for its own plain bookkeeping session (the
    outbox is infrastructure, not an audited business write) and an optional
    *job_session_factory* passed to :func:`run_job` for each job's own audited unit.
    The clock / lease / batch size / retry budget / SKIP-LOCKED flag are injectable for
    tests and for tuning a deployment.
    """

    def __init__(
        self,
        session_factory: Callable[[], Session],
        *,
        job_session_factory: Callable[[], Session] | None = None,
        event_dispatcher: Callable[[EventEnvelope], None] = deliver_event_in_process,
        worker_id: str | None = None,
        clock: Callable[[], datetime] = _utc_now,
        lease_seconds: float = 30.0,
        batch_size: int = 10,
        retry: RetryPolicy | None = None,
        skip_locked: bool = False,
    ) -> None:
        self._session_factory = session_factory
        self._job_session_factory = job_session_factory
        self._event_dispatcher = event_dispatcher
        self._worker_id = worker_id or f"outbox-worker-{uuid.uuid4().hex[:8]}"
        self._clock = clock
        self._lease_seconds = lease_seconds
        self._batch_size = batch_size
        self._retry = retry or RetryPolicy()
        self._skip_locked = skip_locked

    def drain_once(self) -> DrainResult:
        """Claim one batch of due rows, process each, and return the tally."""
        claimed = self._claim_batch()
        dispatched = retried = dead_lettered = lost = 0
        for message in claimed:
            outcome = self._process(message)
            if outcome == STATUS_DISPATCHED:
                dispatched += 1
            elif outcome == STATUS_DEAD_LETTERED:
                dead_lettered += 1
            elif outcome == _LOST:
                lost += 1
            else:
                retried += 1
        return DrainResult(
            claimed=len(claimed),
            dispatched=dispatched,
            retried=retried,
            dead_lettered=dead_lettered,
            lost=lost,
        )

    def run(self, *, max_cycles: int | None = None) -> DrainResult:
        """Drain repeatedly until no rows remain (or *max_cycles* is reached); return totals.

        The worker-container entrypoint runs with ``max_cycles=None``, draining batches
        until the outbox holds no *due* row, then returns — a scheduler / supervisor
        re-invokes it (the design's external-trigger model; a rescheduled row waits out
        its backoff). Tests pass a finite *max_cycles*.
        """
        totals = DrainResult()
        cycles = 0
        while max_cycles is None or cycles < max_cycles:
            result = self.drain_once()
            totals = DrainResult(
                claimed=totals.claimed + result.claimed,
                dispatched=totals.dispatched + result.dispatched,
                retried=totals.retried + result.retried,
                dead_lettered=totals.dead_lettered + result.dead_lettered,
                lost=totals.lost + result.lost,
            )
            cycles += 1
            if result.claimed == 0:
                break
        return totals

    def _claim_batch(self) -> list[_Claimed]:
        """Lease a batch and snapshot it, then close the session (release the lock)."""
        now = self._clock()
        claim_id = f"{self._worker_id}:{uuid.uuid4().hex}"
        lease_until = now + timedelta(seconds=self._lease_seconds)
        with self._session_factory() as session:
            rows = claim_due(
                session,
                claim_id=claim_id,
                now=now,
                lease_until=lease_until,
                limit=self._batch_size,
                skip_locked=self._skip_locked,
            )
            return [
                _Claimed(
                    id=row.id,
                    kind=row.kind,
                    name=row.name,
                    payload=dict(row.payload),
                    attempts=row.attempts,
                    claim_id=claim_id,
                )
                for row in rows
            ]

    def _process(self, message: _Claimed) -> str:
        """Execute one claimed *message*, then finalize its status; return that status."""
        try:
            self._execute(message)
        except Exception as exc:  # noqa: BLE001 - any handler failure becomes a retry / dead-letter
            return self._finalize_failure(message, exc)
        return self._finalize_success(message)

    def _execute(self, message: _Claimed) -> None:
        """Run the message: a job through :func:`run_job`, an event through the dispatcher."""
        if message.kind == KIND_JOB:
            envelope = payload_to_job_envelope(message.payload)
            run_job(
                replace(envelope, attempt=message.attempts + 1),
                session_factory=self._job_session_factory,
            )
        else:
            self._event_dispatcher(payload_to_event_envelope(message.payload))

    def _finalize_success(self, message: _Claimed) -> str:
        """Mark *message* dispatched (only while this worker still holds the lease)."""

        def _mutate(row: OutboxMessage) -> str:
            row.status = STATUS_DISPATCHED
            row.dispatched_at = self._clock()
            return STATUS_DISPATCHED

        return self._finalize(message, _mutate)

    def _finalize_failure(self, message: _Claimed, exc: Exception) -> str:
        """Retry *message* with backoff, or dead-letter it once its budget is spent."""
        retry = self._retry_for(message)

        def _mutate(row: OutboxMessage) -> str:
            row.attempts += 1
            row.last_error = _clip(f"{type(exc).__name__}: {exc}")
            if row.attempts >= retry.max_attempts:
                row.status = STATUS_DEAD_LETTERED
                row.dead_lettered_at = self._clock()
                return STATUS_DEAD_LETTERED
            row.status = STATUS_PENDING
            row.available_at = self._clock() + timedelta(
                seconds=_backoff_seconds(row.attempts, retry)
            )
            return STATUS_PENDING

        return self._finalize(message, _mutate)

    def _finalize(
        self, message: _Claimed, mutate: Callable[[OutboxMessage], str]
    ) -> str:
        """Persist a status transition — but only while this worker still holds the lease.

        A job that outran ``lease_seconds`` may have been reclaimed and finalized by
        another worker; persisting this now-stale worker's outcome would clobber the new
        owner — resurrecting a ``dispatched`` row into ``pending`` (a redundant
        re-dispatch, potentially looping for a consistently slow job) or flipping it to
        ``dead_lettered``, and releasing a lease another worker still holds. So the
        transition is guarded: if ``locked_by`` no longer matches this claim, the worker
        **discards** its outcome (:data:`_LOST`) and the new owner wins (a row that has
        since vanished — e.g. a retention purge between claim and finalize — is likewise
        treated as :data:`_LOST` rather than crashing the cycle). Re-*delivery* already
        happened (at-least-once); this protects only the bookkeeping. Tune
        ``lease_seconds`` above the longest expected job to avoid the redundant work.
        """
        with self._session_factory() as session:
            row = session.get(OutboxMessage, message.id)
            if row is None or row.locked_by != message.claim_id:
                return _LOST
            outcome = mutate(row)
            row.locked_by = None
            row.locked_until = None
            finalize(session)
        return outcome

    def _retry_for(self, message: _Claimed) -> RetryPolicy:
        """The retry budget governing *message*: the job's own, or the worker default."""
        if message.kind == KIND_JOB:
            job = active_job_catalog().get(message.name)
            if job is not None:
                return job.retry
        return self._retry


__all__ = ["DrainResult", "OutboxWorker", "deliver_event_in_process"]
