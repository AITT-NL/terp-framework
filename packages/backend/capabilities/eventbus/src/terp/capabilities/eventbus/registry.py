"""The in-process handler registry — a handler subscribes to a typed catalog event.

A handler is registered against an :class:`~terp.core.EventDefinition` (a typed
catalog constant, never a bare string), keyed by the event's name. The producer
side (:func:`~terp.core.emit`) and this consumer side both reference the same
control-plane catalog, so the no-drift guarantee holds across the bus.

The registry is a process-global, populated at import time by the ``@subscribe``
decorators a module declares. :func:`clear_handlers` exists for diagnostics and
test isolation.
"""

from __future__ import annotations

from collections.abc import Callable

from terp.core import EventDefinition, EventEnvelope

# A handler reacts to one already-validated event fact. It runs synchronously in
# the producer's transaction (see :func:`dispatch_in_process`), so it must not
# commit; raising aborts the producer's unit of work (fail-closed).
HandlerFn = Callable[[EventEnvelope], None]

# event name -> handlers, in registration order.
_HANDLERS: dict[str, list[HandlerFn]] = {}


def subscribe(event: EventDefinition) -> Callable[[HandlerFn], HandlerFn]:
    """Register the decorated function as a handler for *event*.

    *event* is a typed :class:`~terp.core.EventDefinition` from the control-plane
    catalog (the ``terp.arch`` ``events_reference_catalog`` rule forbids a bare
    string here). The same function may subscribe to several events by stacking
    decorators.
    """

    def decorator(handler: HandlerFn) -> HandlerFn:
        _HANDLERS.setdefault(event.name, []).append(handler)
        return handler

    return decorator


def handlers_for(name: str) -> list[HandlerFn]:
    """Return the handlers subscribed to the event *name*, in registration order."""
    return list(_HANDLERS.get(name, ()))


def registered_handlers() -> dict[str, list[HandlerFn]]:
    """Return a copy of the whole registry (diagnostics / tests)."""
    return {name: list(handlers) for name, handlers in _HANDLERS.items()}


def clear_handlers() -> None:
    """Drop every registered handler (diagnostics / test isolation)."""
    _HANDLERS.clear()


__all__ = [
    "HandlerFn",
    "clear_handlers",
    "handlers_for",
    "registered_handlers",
    "subscribe",
]
