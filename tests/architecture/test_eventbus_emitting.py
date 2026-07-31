"""Unit gate for the declarative ``EventEmittingService`` / ``LifecycleEventMap`` (ADR 0009).

Proves a module declares *which* event each write lifecycle emits — no ``super()``,
no imperative ``emit``, no action branching — and the event fires from the
in-transaction ``_after_write`` hook with a payload auto-extracted from the row.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from terp.core import (
    AuditAction,
    BaseService,
    EventCatalog,
    EventDefinition,
    EventEnvelope,
    EventVisibility,
    ModuleSpec,
    Policy,
    create_app,
)
from terp.core.app import BootError
from terp.core.events import EventDispatcher, configure_events, reset_events_runtime

from terp.capabilities.eventbus import EventEmittingService, LifecycleEventMap


class _NotePayload(BaseModel):
    id: uuid.UUID
    title: str


_CREATED = EventDefinition(
    name="notes.note.created", payload_schema=_NotePayload, visibility=EventVisibility.INTERNAL
)


@pytest.fixture(autouse=True)
def _isolate_events() -> Iterator[None]:
    yield
    reset_events_runtime()


def _collecting_dispatcher() -> tuple[list[EventEnvelope], EventDispatcher]:
    seen: list[EventEnvelope] = []

    def dispatcher(session: object, envelope: EventEnvelope, definition: EventDefinition) -> None:
        seen.append(envelope)
        if hasattr(session, "calls"):
            session.calls.append("emit")  # type: ignore[attr-defined]

    return seen, dispatcher


class _SpySession:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def add(self, entity: object) -> None:
        self.calls.append("add")

    def commit(self) -> None:
        self.calls.append("commit")

    def rollback(self) -> None:
        self.calls.append("rollback")

    def refresh(self, entity: object) -> None:
        self.calls.append("refresh")

    def delete(self, entity: object) -> None:
        self.calls.append("delete")


class _NoteService(EventEmittingService):
    event_map = LifecycleEventMap(created=_CREATED)


def test_lifecycle_event_map_for_action() -> None:
    mapping = LifecycleEventMap(created=_CREATED)
    assert mapping.for_action(AuditAction.CREATED) is _CREATED
    assert mapping.for_action(AuditAction.UPDATED) is None
    assert mapping.for_action(AuditAction.DELETED) is None


def test_emits_mapped_event_with_auto_extracted_payload() -> None:
    seen, dispatcher = _collecting_dispatcher()
    configure_events(EventCatalog([_CREATED]), dispatcher=dispatcher)
    note_id = uuid.uuid4()
    entity = SimpleNamespace(id=note_id, title="hello")
    spy = _SpySession()
    _NoteService()._save(spy, entity, AuditAction.CREATED)  # type: ignore[arg-type]
    assert len(seen) == 1
    # The payload is extracted from the row by the event's schema (id + title).
    assert seen[0].payload == {"id": str(note_id), "title": "hello"}
    # …and it rode the transaction: emitted before the commit.
    assert spy.calls.index("emit") < spy.calls.index("commit")


def test_no_emit_for_an_unmapped_action() -> None:
    seen, dispatcher = _collecting_dispatcher()
    configure_events(EventCatalog([_CREATED]), dispatcher=dispatcher)
    entity = SimpleNamespace(id=uuid.uuid4(), title="x")
    _NoteService()._save(_SpySession(), entity, AuditAction.UPDATED)  # type: ignore[arg-type]
    assert seen == []


def test_event_payload_is_overridable_for_a_computed_payload() -> None:
    class _CustomService(EventEmittingService):
        event_map = LifecycleEventMap(created=_CREATED)

        def _event_payload(self, entity: object, definition: EventDefinition) -> object:
            return {"id": str(entity.id), "title": "OVERRIDDEN"}  # type: ignore[attr-defined]

    seen, dispatcher = _collecting_dispatcher()
    configure_events(EventCatalog([_CREATED]), dispatcher=dispatcher)
    entity = SimpleNamespace(id=uuid.uuid4(), title="ignored")
    _CustomService()._save(_SpySession(), entity, AuditAction.CREATED)  # type: ignore[arg-type]
    assert seen[0].payload["title"] == "OVERRIDDEN"


def test_an_event_map_without_the_emitting_base_is_refused_at_class_definition() -> None:
    """The declaration is real, correct, reviewed — and inert. Refuse it, loudly.

    Forgetting ``EventEmittingService`` leaves a service whose ``event_map`` nothing
    reads: the module believes it publishes, every test of the module passes, and the
    events simply never happen. Nothing downstream can detect the difference between
    "no subscriber ran" and "no event was ever emitted", so the kernel refuses the
    class itself.
    """
    with pytest.raises(TypeError, match="which no base it inherits reads"):

        class _ForgotTheBase(BaseService):
            event_map = LifecycleEventMap(created=_CREATED)


def test_the_declaration_is_live_on_a_class_that_inherits_the_emitting_base() -> None:
    assert "event_map" in EventEmittingService.consumes_declarations
    assert _NoteService.event_map.created is _CREATED


def test_an_inert_declaration_is_refused_at_boot_even_if_the_class_slipped_through() -> (
    None
):
    """The class-definition refusal only sees the bases imported so far.

    "Forgot the emitting base" and "never imported the eventbus capability" are the
    same mistake, so the class body can run before anything claims ``event_map``.
    Boot is the first moment the answer is complete, so it asks again.
    """

    class _Slipped(BaseService):
        pass

    _Slipped.event_map = LifecycleEventMap(created=_CREATED)  # type: ignore[attr-defined]
    spec = ModuleSpec(name="notes", policy=Policy.default(), services=[_Slipped])
    with pytest.raises(BootError, match="which no base it inherits reads"):
        create_app([spec])

