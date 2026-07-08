"""terp.capabilities.eventbus — the in-process dispatcher behind the core event seam.

``terp.core`` defines the event *seam* (the typed
:class:`~terp.core.EventDefinition` / :class:`~terp.core.EventCatalog` /
:class:`~terp.core.EventEnvelope` and an :func:`~terp.core.emit` chokepoint whose
default dispatcher does nothing). This opt-in capability supplies the **dispatch**
half: an in-process handler registry (:func:`subscribe`) and a synchronous
:func:`dispatch_in_process` dispatcher that fans a catalog event out to its
subscribers inside the caller's transaction.

Wiring is a single composition-root line —
``create_app(..., event_dispatcher=dispatch_in_process)``. A module subscribes a
handler to a **typed catalog event** (never a string), so the no-drift guarantee
holds end to end. It is a *library* capability (no entry point, no router, no
tables) and depends only on ``terp-core``. A durable outbox + worker can later
replace :func:`dispatch_in_process` as a drop-in dispatcher with no caller change.
"""

from __future__ import annotations

from terp.capabilities.eventbus.dispatcher import current_event_session, dispatch_in_process
from terp.capabilities.eventbus.emitting import EventEmittingService, LifecycleEventMap
from terp.capabilities.eventbus.registry import (
    HandlerFn,
    clear_handlers,
    handlers_for,
    registered_handlers,
    subscribe,
)

__all__ = [
    "EventEmittingService",
    "HandlerFn",
    "LifecycleEventMap",
    "clear_handlers",
    "current_event_session",
    "dispatch_in_process",
    "handlers_for",
    "registered_handlers",
    "subscribe",
]
