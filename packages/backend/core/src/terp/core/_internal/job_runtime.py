"""The job runner: open a session, re-bind the envelope's context, invoke the handler.

This is the kernel's worker half (ADR 0043, the design's §7) — deliberately under
``_internal`` so a module **cannot** import it (the ``no_internal_imports`` rule): only
a :class:`~terp.core.JobQueue` (the in-process default, or a future durable / broker
adapter) drives it. A module reaches background work solely through the typed
:func:`terp.core.enqueue` chokepoint.

The hard part it solves is **context propagation**. The audited ``BaseService``
chokepoint stamps ``created_by_id`` / ``owner_id`` from ``audit_actor_ctx`` and a
tenant-scoped read/write depends on the tenant context — both bound *per HTTP request*.
A background worker has no request, so :func:`run_job`:

* resolves the job from the **active catalog by name** (fail closed if a stale envelope
  names a job a deploy has since removed — the handler is never trusted from the wire),
* re-binds the envelope's ``actor_id`` (or the configured **system actor** when no user
  originated the work), ``request_id``, and ``tenant_id`` (through the registered tenant
  seam), and
* runs the handler inside a fresh, write-guarded session.

So every write a job makes is still audited and actor / tenant stamped with **no**
special-casing — the chokepoint just works — and a failing handler rolls the unit back
(the session is closed without a commit) rather than leaving a half-written, unaudited
graph.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Iterator

from sqlmodel import Session

from terp.core.audit import bind_audit_actor
from terp.core.jobs import (
    JobContext,
    JobEnvelope,
    JobError,
    active_job_catalog,
    active_job_system_actor,
    active_job_tenant_binder,
)
from terp.core.logging import request_id_ctx
from terp.core._internal.engine import get_engine
from terp.core._internal.session_guard import WriteGuardedSession, fresh_write_scope


@contextlib.contextmanager
def _bind_request_id(request_id: str | None) -> Iterator[None]:
    """Bind *request_id* to the logging context for the duration of the block.

    The worker analogue of the request-id middleware: a set/reset pair (not a bare set)
    so the correlation id a job logs under cannot leak across jobs sharing a worker
    thread, and so an emitted audit / event record carries the originating request id.
    """
    token = request_id_ctx.set(request_id)
    try:
        yield
    finally:
        request_id_ctx.reset(token)


def _default_session_factory() -> Session:
    """A fresh, write-guarded session on the process engine (the request-style session)."""
    return WriteGuardedSession(get_engine())


def run_job(
    envelope: JobEnvelope,
    *,
    session_factory: Callable[[], Session] | None = None,
) -> None:
    """Resolve, context-bind, and execute one :class:`JobEnvelope` (the worker step).

    Looks the job up in the **active catalog by name** (a :class:`JobError` if it is not
    registered — a stale envelope after a deploy must not silently no-op), rebuilds the
    payload from the canonical schema, then opens a session and re-binds the envelope's
    actor (falling back to the configured system actor), request id, and tenant before
    handing a :class:`JobContext` to the handler. The session is opened from
    *session_factory* (tests inject a synthetic engine); a missing one defaults to the
    write-guarded process session. The session is closed on exit, so an exception from
    the handler unwinds the whole unit (no partial, unaudited commit).
    """
    job = active_job_catalog().get(envelope.name)
    if job is None:
        raise JobError(
            f"job {envelope.name!r} is not registered in the active JobCatalog; "
            "a worker cannot resolve a handler for it (was it removed by a deploy?)"
        )
    payload = job.payload_schema.model_validate(dict(envelope.payload))
    actor_id = envelope.actor_id if envelope.actor_id is not None else active_job_system_actor()
    tenant_binder = active_job_tenant_binder()
    factory = session_factory if session_factory is not None else _default_session_factory
    with factory() as session:
        with (
            bind_audit_actor(actor_id),
            _bind_request_id(envelope.request_id),
            fresh_write_scope(),
            tenant_binder(envelope.tenant_id)
            if tenant_binder is not None
            else contextlib.nullcontext(),
        ):
            context = JobContext(
                session=session,
                actor_id=actor_id,
                tenant_id=envelope.tenant_id,
                request_id=envelope.request_id,
                attempt=envelope.attempt,
            )
            job.handler(context, payload)


__all__ = ["run_job"]
