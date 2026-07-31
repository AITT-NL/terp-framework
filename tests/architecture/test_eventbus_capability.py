"""Unit gate for ``terp.capabilities.eventbus`` (the in-process dispatcher + registry).

Exercises the handler registry (``subscribe`` / ``handlers_for`` /
``registered_handlers`` / ``clear_handlers``) and ``dispatch_in_process`` (fan-out
to zero, one, and many handlers), plus the end-to-end seam: ``configure_events``
installs the dispatcher and ``emit`` drives a real subscriber. Isolated from the
process-global registry so the example app's own handlers survive the suite.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from pydantic import BaseModel

from terp.core import (
    ControlPlane,
    EventCatalog,
    EventDefinition,
    EventEnvelope,
    EventVisibility,
    ModuleSpec,
    Policy,
    create_app,
    emit,
)
from terp.core.app import BootError
from terp.core.events import reset_events_runtime, subscribed_event_names

from terp.capabilities.eventbus import (
    clear_handlers,
    current_event_session,
    dispatch_in_process,
    handlers_for,
    registered_handlers,
    subscribe,
)
from terp.capabilities.eventbus import registry as registry_module
from terp.core.events import configure_events


class _Payload(BaseModel):
    id: str = ""


_CREATED = EventDefinition(
    name="widgets.widget.created",
    payload_schema=_Payload,
    visibility=EventVisibility.INTERNAL,
)


@pytest.fixture(autouse=True)
def _isolate_registry_and_runtime() -> Iterator[None]:
    """Snapshot the global handler registry, run on a clean one, then restore it."""
    saved = registry_module.registered_handlers()
    clear_handlers()
    try:
        yield
    finally:
        registry_module._HANDLERS.clear()
        registry_module._HANDLERS.update(saved)
        reset_events_runtime()


def test_subscribe_registers_a_handler() -> None:
    received: list[EventEnvelope] = []

    @subscribe(_CREATED)
    def handler(envelope: EventEnvelope) -> None:
        received.append(envelope)

    assert [fn.__name__ for fn in handlers_for("widgets.widget.created")] == ["handler"]
    assert registered_handlers() == {"widgets.widget.created": [handler]}


def test_handlers_for_unknown_event_is_empty() -> None:
    assert handlers_for("nothing.here") == []


def test_clear_handlers_empties_the_registry() -> None:
    subscribe(_CREATED)(lambda envelope: None)
    assert registered_handlers()
    clear_handlers()
    assert registered_handlers() == {}


def test_dispatch_in_process_fans_out_to_every_handler() -> None:
    calls: list[str] = []

    @subscribe(_CREATED)
    def first(envelope: EventEnvelope) -> None:
        calls.append("first")

    @subscribe(_CREATED)
    def second(envelope: EventEnvelope) -> None:
        calls.append("second")

    envelope = EventEnvelope(
        name="widgets.widget.created",
        visibility=EventVisibility.INTERNAL,
        payload={"id": "1"},
    )
    dispatch_in_process(object(), envelope, _CREATED)  # type: ignore[arg-type]
    assert calls == ["first", "second"]


def test_dispatch_in_process_with_no_handler_is_a_noop() -> None:
    envelope = EventEnvelope(
        name="widgets.widget.created",
        visibility=EventVisibility.INTERNAL,
        payload={"id": "1"},
    )
    # No subscriber: nothing happens, no error.
    dispatch_in_process(object(), envelope, _CREATED)  # type: ignore[arg-type]


def test_emit_drives_the_in_process_dispatcher_end_to_end() -> None:
    received: list[EventEnvelope] = []

    @subscribe(_CREATED)
    def handler(envelope: EventEnvelope) -> None:
        received.append(envelope)

    configure_events(EventCatalog([_CREATED]), dispatcher=dispatch_in_process)
    emit(object(), event=_CREATED, payload={"id": "42"})  # type: ignore[arg-type]
    assert len(received) == 1
    assert received[0].payload == {"id": "42"}


def test_a_raising_handler_propagates_fail_closed() -> None:
    @subscribe(_CREATED)
    def boom(envelope: EventEnvelope) -> None:
        raise RuntimeError("handler failed")

    configure_events(EventCatalog([_CREATED]), dispatcher=dispatch_in_process)
    with pytest.raises(RuntimeError, match="handler failed"):
        emit(object(), event=_CREATED, payload={"id": "1"})  # type: ignore[arg-type]


def test_current_event_session_exposes_the_producer_session_during_dispatch() -> None:
    # A handler that needs to fold transactional follow-up work into the producer's
    # transaction reads the bound session through the seam (no dual-write).
    producer_session = object()
    seen: list[object] = []

    @subscribe(_CREATED)
    def handler(envelope: EventEnvelope) -> None:
        seen.append(current_event_session())

    envelope = EventEnvelope(
        name="widgets.widget.created",
        visibility=EventVisibility.INTERNAL,
        payload={"id": "1"},
    )
    dispatch_in_process(producer_session, envelope, _CREATED)  # type: ignore[arg-type]
    assert seen == [producer_session]


def test_current_event_session_outside_a_dispatch_fails_closed() -> None:
    # There is no producer session outside an in-process dispatch, so the seam refuses
    # rather than handing back a wrong / None session.
    with pytest.raises(RuntimeError, match="in-process event dispatch"):
        current_event_session()


# --------------------------------------------------------------------------- #
# the boot cross-check: a declared subscription must have a registered handler
# --------------------------------------------------------------------------- #
def test_a_declared_subscription_without_a_handler_is_refused_at_boot() -> None:
    """Declaring `subscribes` and forgetting the handler import must fail the boot.

    The handler registers as a side effect of importing its module. Drop that import
    and the manifest still claims the subscription while nothing listens — an app that
    is wrong in a way no request, log line or test of the module can reveal.
    """
    spec = ModuleSpec(
        name="widgets", policy=Policy.default(), subscribes=[_CREATED]
    )
    with pytest.raises(BootError, match="no handler is registered"):
        create_app(
            [spec],
            control_plane=ControlPlane(events=EventCatalog([_CREATED])),
        )


def test_a_declared_subscription_with_a_registered_handler_boots() -> None:
    @subscribe(_CREATED)
    def handler(envelope: EventEnvelope) -> None:  # pragma: no cover - never dispatched
        return None

    spec = ModuleSpec(
        name="widgets", policy=Policy.default(), subscribes=[_CREATED]
    )
    create_app(
        [spec],
        control_plane=ControlPlane(events=EventCatalog([_CREATED])),
    )


def test_the_registry_reports_its_subscriptions_to_the_kernel() -> None:
    @subscribe(_CREATED)
    def handler(envelope: EventEnvelope) -> None:  # pragma: no cover - never dispatched
        return None

    assert _CREATED.name in subscribed_event_names()
