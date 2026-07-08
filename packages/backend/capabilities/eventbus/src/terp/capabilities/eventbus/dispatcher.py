"""The in-process event dispatcher — the seam ``create_app`` installs.

``create_app(..., event_dispatcher=dispatch_in_process)`` installs this on the core
event seam, so each :func:`~terp.core.emit` fans the event out to every in-process
handler subscribed to it. Handlers run **synchronously in the caller's
transaction**: the dispatcher never commits, and a handler that raises propagates,
aborting the producer's unit of work rather than half-delivering (fail-closed).

Because a handler runs *inside the producer's open transaction*, it may reach that same
session through :func:`current_event_session` to fold **transactional follow-up work** —
e.g. ``enqueue(session, job=…)`` for a durable webhook delivery — into the same atomic
unit (no dual-write). The session is bound only for the duration of the synchronous
fan-out, exactly like the request-scoped ``audit_actor_ctx`` context.
"""

from __future__ import annotations

from contextvars import ContextVar

from sqlmodel import Session

from terp.core import EventDefinition, EventEnvelope

from terp.capabilities.eventbus.registry import handlers_for

# The producer's session, bound for the duration of an in-process dispatch so a handler can
# reach the open transaction the business write is running in. A ContextVar (it follows the
# synchronous call stack) defaulting to ``None`` outside a dispatch, mirroring the
# request-scoped context vars in ``terp.core``.
_event_session: ContextVar[Session | None] = ContextVar(
    "terp_event_dispatch_session", default=None
)


def current_event_session() -> Session:
    """Return the producer's session for the in-flight event dispatch (fail closed).

    A ``@subscribe`` handler calls this to obtain the **same** session — and therefore the
    same open transaction — the business write is running in, so a follow-up such as
    ``enqueue(session, job=…)`` commits atomically with the write that emitted the event (no
    dual-write). It is valid only while :func:`dispatch_in_process` is fanning an event out
    synchronously; outside an in-process dispatch there is no producer session, so it raises
    :class:`RuntimeError` rather than returning a wrong or ``None`` session.
    """
    session = _event_session.get()
    if session is None:
        raise RuntimeError(
            "current_event_session() is only available inside an in-process event dispatch; "
            "a handler that needs the producer's session must run under dispatch_in_process "
            "(synchronous, in the business write's transaction)"
        )
    return session


def dispatch_in_process(
    session: Session, envelope: EventEnvelope, definition: EventDefinition
) -> None:
    """Deliver *envelope* to every in-process handler subscribed to its event.

    The *session* and *definition* satisfy the dispatcher seam contract (a durable outbox
    rides the session). Handlers receive only the typed envelope, but may reach the
    producer's *session* through :func:`current_event_session` to fold transactional
    follow-up work into the same atomic unit. The session is bound for the synchronous
    fan-out and cleared on exit (token-based reset), so it never leaks across dispatches
    sharing a worker thread.
    """
    token = _event_session.set(session)
    try:
        for handler in handlers_for(envelope.name):
            handler(envelope)
    finally:
        _event_session.reset(token)


__all__ = ["current_event_session", "dispatch_in_process"]
